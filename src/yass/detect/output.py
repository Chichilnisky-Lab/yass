import logging
import os
import numpy as np

def gather_result(fname_save, batch_files_dir, dedup_dir):
    
    logger = logging.getLogger(__name__)
    
    n_batches = len(os.listdir(batch_files_dir))
    spike_index_postkill = []
    n_spikes_detected = 0
    for batch_id in range(n_batches):

        # detection index 
        fname_index = os.path.join(
            batch_files_dir,
            "detect_"+str(batch_id).zfill(5)+'.npz')
        detect_data =  np.load(fname_index)
        spike_index = detect_data['spike_index']
        minibatch_loc = detect_data['minibatch_loc']

        # dedup index
        fname_dedup = os.path.join(
            dedup_dir,
            "dedup_"+str(batch_id).zfill(5)+'.npy')
        dedup_idx = np.load(fname_dedup)

        for ctr in range(len(spike_index)):
            spike_index_temp = spike_index[ctr][dedup_idx[ctr]]
            t_start, t_end = minibatch_loc[ctr]

            n_spikes_detected += len(spike_index_temp)

            idx_keep = np.logical_and(
                spike_index_temp[:, 0] >= t_start,
                spike_index_temp[:, 0] < t_end)
            spike_index_temp = spike_index_temp[idx_keep]
            spike_index_postkill.append(spike_index_temp)


    spike_index_postkill = np.vstack(spike_index_postkill)
    
    logger.info('{} spikes detected'.format(n_spikes_detected))
    logger.info('{} spikes after deduplication'.format(len(spike_index_postkill)))

    np.save(fname_save, spike_index_postkill)
        
    