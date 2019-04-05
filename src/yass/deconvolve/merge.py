import os
import numpy as np
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import tqdm
import parmap
import scipy
import networkx as nx
import logging
import multiprocessing as mp

from diptest import diptest as dp

from yass import read_config
from yass.template import shift_chans, align_get_shifts_with_ref
from yass.deconvolve.correlograms_phy import compute_correlogram
from yass.deconvolve.notch import notch_finder

from statsmodels import robust
from scipy.signal import argrelmin
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis as LDA

#from yass.cluster.util import read_spikes

class TemplateMerge(object):

    def __init__(self, 
                 templates, 
                 results_fname,
                 CONFIG, 
                 deconv_chunk_dir,
                 iteration=0, recompute=False, affinity_only=False):
      
                               
        """
        parameters:
        -----------
        templates: numpy.ndarray shape (K, C, T)
            templates
        spike_train: numpy.ndarray shape (N, 2)
            First column is times and second is cluster id.
        """
        
        # 
        self.deconv_chunk_dir = deconv_chunk_dir
        self.results_fname = results_fname
        
        # set filename to residual file
        self.filename_residual = os.path.join(deconv_chunk_dir.replace('merge',''), 
                                     'residual.bin')
        self.CONFIG = CONFIG
        self.iteration = iteration

        self.templates = templates.transpose(2,0,1)
        print ("  templates in: ", templates.shape)
        self.recompute=recompute
        self.n_unit = self.templates.shape[0]
        self.n_check = min(10, self.n_unit)

        # # Cat: Pass only filenames in: 
        # self.templates_upsampled = templates_upsampled.transpose(2,0,1)
        # self.spike_train = spike_train
        # self.spike_train_upsampled = spike_train_upsampled

        
        # TODO find pairs that for proposing merges
        # get temp vs. temp affinity, use for merge proposals
        fname = os.path.join(deconv_chunk_dir, 
                             'affinity_'+str(self.iteration)+'.npy')
                             
        if os.path.exists(fname)==False or self.recompute:
            print ("  computing affinity matrix...") 
            self.affinity_matrix = template_dist_linear_align(
                self.templates)
            print ("  done computing affinity matrix")
            np.save(fname, self.affinity_matrix)
        else:
            print ("  affinity matrix prev computed...loading")
            self.affinity_matrix = np.load(fname)
        
        if affinity_only:
            return 
                
        # Template norms
        self.norms = np.linalg.norm(
            self.templates.reshape(self.templates.shape[0], -1), axis=1)

        # Distance metric with diagonal set to large numbers
        dist_mat = np.zeros_like(self.affinity_matrix)
        for i in range(self.n_unit):
            dist_mat[i, i] = 1e4
        dist_mat += self.affinity_matrix
        
        # proposed merge pairs
        #print ("  computing hungarian alg assignment...")
        fname = os.path.join(deconv_chunk_dir,
                             'merge_candidate_'+str(self.iteration)+'.npy')

        if os.path.exists(fname)==False:
            print ( "  TODO: write faster merge algorithm...")

            #self.merge_candidate = scipy.optimize.linear_sum_assignment(dist_mat)[1]
            #self.merge_candidate = self.find_merge_candidates()
            self.merge_candidate = np.argsort(dist_mat, axis=1)[:,:self.n_check]
            np.save(fname, self.merge_candidate)
        else:
            self.merge_candidate = np.load(fname)

        # Check the ratio of distance between proposed pairs compared to
        # their norms, if the value is greater that .3 then test the unimodality
        # test on the distribution of distinces of residuals.
        self.dist_norm_ratio = dist_mat[
            np.tile(np.arange(self.n_unit)[:, np.newaxis], [1, self.n_check]),
            self.merge_candidate] / (self.norms[self.merge_candidate] + self.norms[:, np.newaxis])

        fname = os.path.join(deconv_chunk_dir,
                             'dist_norm_ratio_'+str(self.iteration)+'.npy')
        np.save(fname, self.dist_norm_ratio)

    def find_merge_candidates(self):
        print ( "  TODO: write serial merging algorithm...")
        
        pass


    def get_merge_pairs(self):
        ''' Run all pairs of merge candidates through the l2 feature computation        
        '''

        units_1 = np.tile(np.arange(self.n_unit)[:, np.newaxis], [1, self.n_check])
        units_2 = self.merge_candidate

        # exclude when distance between the pair is large
        idx1 = self.dist_norm_ratio < 0.5
        
        # exclude when one of the pair has ptp less than 4
        ptps = self.templates.ptp(1).max(1)
        big_units = (ptps > 4)
        idx2 = np.logical_and(big_units[units_1], big_units[units_2])

        idx = np.logical_and(idx1, idx2)
        units_1 = units_1[idx]
        units_2 = units_2[idx]

        # get unique pairs only for comparison
        unique_pairs = []
        for x,y in zip(units_1, units_2):
            if [x, y] not in unique_pairs and [y, x] not in unique_pairs:
                unique_pairs.append([x, y])
        
        fname = os.path.join(self.deconv_chunk_dir,
                             'merge_list_'+str(self.iteration)+'.npy')
                             
        print ("  computing l2features and distances in parallel")
        # Cat: TODO: does python2 like list(zip())?
        if os.path.exists(fname)==False or self.recompute:
            if self.CONFIG.resources.multi_processing:
                merge_list = parmap.map(self.merge_templates_parallel2, 
                             list(zip(unique_pairs)),
                             processes=self.CONFIG.resources.n_processors,
                             pm_pbar=True)
            # single core version
            else:
                merge_list = []
                for ii in range(len(units_1)):
                    print (" unit: ", ii)
                    temp = self.merge_templates_parallel2([unique_pairs[ii]])
                    merge_list.append(temp)
            np.save(fname, np.array(merge_list))
        else:
            merge_list = np.load(fname)
            
        return merge_list


    # def get_merge_pairs_units(self):
        # ''' Check all units against nearest units in increasing distance.
            # This algorithm does not use hugnarian algorithm to assign 
            # candidates; rather, check until diptests start to become too low
        # '''
        
        # units = np.where(self.dist_norm_ratio < 0.5)[0]
        
        # fname = os.path.join(self.deconv_chunk_dir,
                             # 'merge_list_'+str(self.iteration)+'.npy')
                             
        # print ("  computing l2features and distances in parallel")
        # print (units.shape)
        # print (self.merge_candidate.shape)
        # if os.path.exists(fname)==False or self.recompute:
            # if self.CONFIG.resources.multi_processing:
                # merge_list = parmap.map(self.merge_templates_parallel, 
                             # list(zip(units, self.merge_candidate[units])),
                             # processes=self.CONFIG.resources.n_processors,
                             # pm_pbar=True)
            # # single core version
            # else:
                # merge_list = []
                # for unit in units:
                    # temp = self.merge_templates_parallel(
                                        # [unit, self.merge_candidate[unit]])
                    # merge_list.append(temp)
            # np.save(fname, merge_list)
        # else:
            # merge_list = np.load(fname)
            
        # return merge_list


    # def merge_templates_parallel(self, data_in):
        # """Whether to merge two templates or not.

        # parameters:
        # -----------
        # unit1: int
            # Index of the first template
        # unit2: int
            # Index of the second template
        # threshold: float
            # The threshold for the unimodality test.
        # n_samples: int
            # Maximum number of cleaned spikes from each unit.

        # returns:
        # --------
        # Bool. If True, the two templates should be merged. False, otherwise.
        # """
        
        # # Cat: TODO: read from CONFIG
        # threshold=0.95
        
        # unit1 = data_in[0]
        # unit2 = data_in[1]

        # fname = os.path.join(self.deconv_chunk_dir, 
                    # 'l2features_'+str(unit1)+'_'+str(unit2)+'_'+str(self.iteration)+'.npz')
        # print (fname)
        # if os.path.exists(fname)==False or self.recompute:
        
            # l2_features, spike_ids = get_l2_features(
                # self.filename_residual, self.spike_train,
                # self.spike_train_upsampled,
                # self.templates, self.templates_upsampled,
                # unit1, unit2)

            # dp_val, _ = test_unimodality(l2_features, spike_ids)
            # #print (" units: ", unit1, unit2, " dp_val: ", dp_val)
            # # save data
            # np.savez(fname,
                     # #spt1_idx=spt1_idx, spt2_idx=spt2_idx,
                     # #spikes_1=spikes_1, spikes_2=spikes_2,
                     # spike_ids=spike_ids,
                     # l2_features=l2_features,
                     # dp_val=dp_val)

        # else:
            # data = np.load(fname)
            # dp_val = data['dp_val']
        
        # if dp_val > threshold:
            # return (unit1, unit2)

        # return None



    def merge_templates_parallel2(self, data_in):
        """Whether to merge two templates or not.
        """
        
        # Cat: TODO: read from CONFIG
        threshold=0.95
        
        # load these data arrays on each core (don't pass them into pipeline)
        # Cat: TODO: maybe also want to read templates ...
        data = np.load(self.results_fname)
        templates_upsampled = data['templates_upsampled'].transpose(2,0,1)
        spike_train = data['spike_train']
        spike_train_upsampled = data['spike_train_upsampled']
                    
        return_vals = []
        for data_ in data_in:
            unit1 = data_[0]
            unit2 = data_[1]
            
            fname = os.path.join(self.deconv_chunk_dir, 
                        'l2features_'+str(unit1)+'_'+str(unit2)+'_'+str(self.iteration)+'.npz')
            if os.path.exists(fname)==False or self.recompute:
                
                xcor = compute_correlogram(
                    np.hstack((unit1, unit2)), spike_train)
                if xcor.shape[0] == 1:
                    xcor = xcor[0,0]
                elif xcor.shape[0] > 1:
                    xcor = xcor[1,0]
                    
                notch, pval1, pval2 = notch_finder(xcor)

                if pval1 < 0.05:
                    l2_features, spike_ids = get_l2_features(
                        self.filename_residual,
                        spike_train,
                        spike_train_upsampled,
                        self.templates,
                        templates_upsampled,
                        unit1, unit2)

                    dp_val, _ = test_unimodality(l2_features, spike_ids)
                    
                else:
                    dp_val = 0
                    spike_ids = None
                    l2_features = None

                # save data
                np.savez(fname,
                         notch_pval=pval1,
                         spike_ids=spike_ids,
                         l2_features=l2_features,
                         dp_val=dp_val)

            else:
                data = np.load(fname)
                dp_val = data['dp_val']
        
            if dp_val > threshold:
                return_vals.append([unit1, unit2])
            else:
                return_vals.append(None)

        return (return_vals)


        
    def merge_templates_parallel_units(self):
        
        pass


def get_l2_features(filename_residual, spike_train, spike_train_upsampled,
                    templates, templates_upsampled, unit1, unit2, n_samples=2000):
    
    _, spike_size, n_channels = templates.shape
    
    # get n_sample of cleaned spikes per template.
    spt1_idx = np.where(spike_train[:, 1] == unit1)[0]
    spt2_idx = np.where(spike_train[:, 1] == unit2)[0]
    
    # subsample
    if len(spt1_idx) + len(spt2_idx) > n_samples:
        ratio = len(spt1_idx)/(len(spt1_idx)+len(spt2_idx))
        
        n_samples1 = int(n_samples*ratio)
        n_samples2 = n_samples - n_samples1

        spt1_idx = np.random.choice(
            spt1_idx, n_samples1, False)
        spt2_idx = np.random.choice(
            spt2_idx, n_samples2, False)
    
    spt1 = spike_train[spt1_idx, 0]
    spt2 = spike_train[spt2_idx, 0]

    units1 = spike_train_upsampled[spt1_idx, 1]
    units2 = spike_train_upsampled[spt2_idx, 1]

    spikes_1, _ = read_spikes(
        filename_residual, spt1, n_channels, spike_size,
        units1, templates_upsampled, residual_flag=True)
    spikes_2, _ = read_spikes(
        filename_residual, spt2, n_channels, spike_size,
        units2, templates_upsampled, residual_flag=True)

    spike_ids = np.append(
        np.zeros(len(spikes_1), 'int32'),
        np.ones(len(spikes_2), 'int32'),
        axis=0)
    
    l2_features = template_spike_dist_linear_align(
        templates[[unit1, unit2], :, :],
        np.append(spikes_1, spikes_2, axis=0))
    
    return l2_features.T, spike_ids


def test_unimodality(pca_wf, assignment, max_spikes = 10000):

    '''
    Parameters
    ----------
    pca_wf:  pca projected data
    ssignment:  spike assignments
    max_spikes: optional
    '''

    #n_samples = np.max(np.unique(assignment, return_counts=True)[1])

    # compute diptest metric on current assignment+LDA

    
    ## find indexes of data
    #idx1 = np.where(assignment==0)[0]
    #idx2 = np.where(assignment==1)[0]
    #min_spikes = min(idx1.shape, idx2.shape)[0]

    # limit size difference between clusters to maximum of 5 times
    #ratio = 1
    #idx1=idx1[:min_spikes*ratio][:max_spikes]
    #idx2=idx2[:min_spikes*ratio][:max_spikes]

    #idx_total = np.concatenate((idx1,idx2))

    ## run LDA on remaining data
    lda = LDA(n_components = 1)
    #print (pca_wf[idx_total].shape, assignment[idx_total].shape) 
    #trans = lda.fit_transform(pca_wf[idx_total], assignment[idx_total])
    trans = lda.fit_transform(pca_wf, assignment).ravel()
    
    _, n_spikes = np.unique(assignment, return_counts=True)
    id_big = np.argmax(n_spikes)
    id_small = np.argmin(n_spikes)
    n_diff = n_spikes[id_big] - n_spikes[id_small]

    repeat = int(np.ceil(np.max(n_spikes)/np.min(n_spikes)))
    idx_big = np.where(assignment == id_big)[0]
    pvals = np.zeros(repeat)
    for j in range(repeat):
        idx_remove = np.random.choice(idx_big, n_diff, replace=False)
        pvals[j] = dp(np.delete(trans, idx_remove))[1]

    ## also compute gaussanity of distributions
    ## first pick the number of bins; this metric is somewhat sensitive to this
    # Cat: TODO number of bins is dynamically set; need to work on this
    #n_bins = int(np.log(n_samples)*3)
    #y1 = np.histogram(trans, bins = n_bins)
    #normtest = stats.normaltest(y1[0])

    return np.median(pvals), trans#, assignment[idx_total]#, normtest[1]


def template_spike_dist(templates, spikes, jitter=0, upsample=1, vis_ptp=2., **kwargs):
    """compares the templates and spikes.

    parameters:
    -----------
    templates: numpy.array shape (K, C, T)
    spikes: numpy.array shape (M, C, T)
    jitter: int
        Align jitter amount between the templates and the spikes.
    upsample int
        Upsample rate of the templates and spikes.
    """
    # Only use the channels that the template has visibility.
    vis_chan = templates.ptp(-1).max(0) >= vis_ptp
    templates = templates[:, vis_chan, :]
    spikes = spikes[:, vis_chan, :]
    spikes_old = spikes.copy()

    print ("  upsampling")
    # Upsample the templates
    if upsample > 1:
        n_t = templates.shape[-1]
        templates = scipy.signal.resample(templates, n_t * upsample, axis=-1)
        spikes = scipy.signal.resample(spikes, n_t * upsample, axis=-1)
        
    n_times = templates.shape[-1]
    n_chan = templates.shape[1]
    n_unit = templates.shape[0]
    n_spikes = spikes.shape[0]

    # Get a smaller window around the templates.
    if jitter > 0:
        jitter = jitter * upsample
        templates = templates[:, :, jitter // 2:-jitter // 2]
        idx = np.arange(n_times - jitter) + np.arange(jitter)[:, None]
        # indices: [spike number, channel, jitter, time]
        spikes = spikes[:, :, idx].transpose([0, 2, 1, 3]).reshape(
            [-1, n_chan, n_times - jitter])

    print ("  cdist computation")
    # Pairwise distance of templates and spikes
    dist = scipy.spatial.distance.cdist(
            templates.reshape([n_unit, -1]),
            spikes.reshape([n_spikes * max(jitter, 1), -1]),
            **kwargs)
    print ("  done cdist computation")

    # Get best jitter distance
    if jitter > 0:
        return dist.reshape([n_unit, n_spikes, jitter]).min(axis=-1)
    return dist


def template_spike_dist_linear_align(templates, spikes, vis_ptp=2.):
    """compares the templates and spikes.

    parameters:
    -----------
    templates: numpy.array shape (K, T, C)
    spikes: numpy.array shape (M, T, C)
    jitter: int
        Align jitter amount between the templates and the spikes.
    upsample int
        Upsample rate of the templates and spikes.
    """

    #print ("templates: ", templates.shape)
    #print ("spikes: ", spikes.shape)
    # new way using alignment only on max channel
    # maek reference template based on templates
    max_idx = templates.ptp(1).max(1).argmax(0)
    ref_template = templates[max_idx]
    max_chan = ref_template.ptp(0).argmax(0)
    ref_template = ref_template[:, max_chan]

    # stack template max chan waveforms only
    #max_chans = templates.ptp(2).argmax(1)
    #temps = []
    #for k in range(max_chans.shape[0]):
    #    temps.append(templates[k,max_chans[k]])
    #temps = np.vstack(temps)
    #print ("tempsl stacked: ", temps.shape)
    
    #upsample_factor=5
    best_shifts = align_get_shifts_with_ref(
        templates[:, :, max_chan],
        ref_template, nshifts = 21)
    #print (" best shifts: ", best_shifts.shape)
    templates = shift_chans(templates, best_shifts)
    #print ("  new aligned templates: ", templates_aligned.shape)

    # find spike shifts
    #max_chans = spikes.ptp(2).argmax(1)
    #print ("max chans: ", max_chans.shape)
    #spikes_aligned = []
    #for k in range(max_chans.shape[0]):
    #    spikes_aligned.append(spikes[k,max_chans[k]])
    #spikes_aligned = np.vstack(spikes_aligned)
    #print ("spikes aligned max chan: ", spikes_aligned.shape)
    best_shifts = align_get_shifts_with_ref(
        spikes[:,:,max_chan], ref_template, nshifts = 21)
    spikes = shift_chans(spikes, best_shifts)
    #print ("  new aligned spikes: ", spikes_aligned.shape)
    
    n_unit = templates.shape[0]
    n_spikes = spikes.shape[0]

    vis_chan = np.where(templates.ptp(1).max(0) >= vis_ptp)[0]
    templates = templates[:, :, vis_chan].reshape(n_unit, -1)
    spikes = spikes[:, :, vis_chan].reshape(n_spikes, -1)

    if templates.shape[0] == 1:
        idx = np.arange(templates.shape[1])
    elif templates.shape[0] == 2:
        diffs = np.abs(np.diff(templates, axis=0)[0])
        
        idx = np.where(diffs > 1.5)[0]
        min_diff_points = 5
        if len(idx) < 5:
            idx = np.argsort(diffs)[-min_diff_points:]
    else:
        diffs = np.mean(np.abs(
            templates-templates[max_idx][None]), axis=0)
        
        idx = np.where(diffs > 1.5)[0]
        min_diff_points = 5
        if len(idx) < 5:
            idx = np.argsort(diffs)[-min_diff_points:]
                       
    templates = templates[:, idx]
    spikes = spikes[:, idx]

    dist = scipy.spatial.distance.cdist(templates, spikes)

    return dist

def template_dist_linear_align(templates, distance=None, units=None, max_shift=5, step=0.5):

    K, R, C = templates.shape

    shifts = np.arange(-max_shift,max_shift+step,step)
    ptps = templates.ptp(1)
    max_chans = np.argmax(ptps, 1)

    shifted_templates = np.zeros((len(shifts), K, R, C))
    for ii, s in enumerate(shifts):
        shifted_templates[ii] = shift_chans(templates, np.ones(K)*s)

    if distance is None:
        distance = np.ones((K, K))*1e4
    if units is None:
        units = np.arange(K)

    for k in units:
        candidates = np.abs(ptps[:, max_chans[k]] - ptps[k, max_chans[k]])/ptps[k,max_chans[k]] < 0.5
        
        dist = np.min(np.sum(np.square(
            templates[k][np.newaxis, np.newaxis] - shifted_templates[:, candidates]),
                             axis=(2,3)), 0)
        dist = np.sqrt(dist)
        distance[k, candidates] = dist
        distance[candidates, k] = dist
        
    return distance    
