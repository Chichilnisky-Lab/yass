import tensorflow as tf
import numpy as np

from .remove import remove_duplicate_spikes_by_energy
from .score import get_score

from ..geometry import order_channels_by_distance

from . import NeuralNetDetector, NeuralNetTriage


def nn_detection(X, neighbors, geom, temporal_features, temporal_window,
                 th_detect, th_triage, detector_filename, autoencoder_filename,
                 triage_filename):
    """Detect spikes using a neural network

    Parameters
    ----------

    Returns
    -------
    """
    nnd = NeuralNetDetector(detector_filename, autoencoder_filename)
    nnt = NeuralNetTriage(triage_filename)

    T, C = X.shape

    # neighboring channel info
    nneigh = np.max(np.sum(neighbors, 0))
    c_idx = np.ones((C, nneigh), 'int32')*C
    for c in range(C):
        ch_idx, temp = order_channels_by_distance(
            c, np.where(neighbors[c])[0], geom)
        c_idx[c, :ch_idx.shape[0]] = ch_idx

    # input
    x_tf = tf.placeholder("float", [T, C])

    # detect spike index
    local_max_idx_tf = nnd.get_spikes(
        x_tf, T, nneigh, c_idx, temporal_window, th_detect)

    # get score train
    score_train_tf = nnd.get_score_train(x_tf)

    # get energy for detected index
    energy_tf = tf.reduce_sum(tf.square(score_train_tf), axis=2)
    energy_val_tf = tf.gather_nd(energy_tf, local_max_idx_tf)

    # get triage probability
    triage_prob_tf = nnt.triage_prob(x_tf, T, nneigh, c_idx)

    # gather all results above
    result = (local_max_idx_tf, score_train_tf, energy_val_tf, triage_prob_tf)

    # remove duplicates
    energy_train_tf = tf.placeholder("float", [T, C])
    spike_index_tf = remove_duplicate_spikes_by_energy(
        energy_train_tf, T, c_idx, temporal_window)

    # get score
    score_train_placeholder = tf.placeholder(
        "float", [T, C, temporal_features])
    spike_index_clear_tf = tf.placeholder("int64", [None, 2])
    score_tf = get_score(score_train_placeholder,
                         spike_index_clear_tf, T,
                         temporal_features, c_idx)

    ###############################
    # get values of above tensors #
    ###############################

    with tf.Session() as sess:

        nnd.saver.restore(sess, nnd.path_to_detector_model)
        nnd.saver_ae.restore(sess, nnd.path_to_ae_model)
        nnt.saver.restore(sess, nnt.path_to_triage_model)

        local_max_idx, score_train, energy_val, triage_prob = sess.run(
            result, feed_dict={x_tf: X})

        energy_train = np.zeros((T, C))
        energy_train[local_max_idx[:, 0], local_max_idx[:, 1]] = energy_val
        spike_index = sess.run(spike_index_tf, feed_dict={
                               energy_train_tf: energy_train})

        idx_clean = triage_prob[spike_index[
            :, 0], spike_index[:, 1]] > th_triage

        spike_index_clear = spike_index[idx_clean]
        spike_index_collision = spike_index[~idx_clean]

        score = sess.run(score_tf, feed_dict={
                         score_train_placeholder: score_train,
                         spike_index_clear_tf: spike_index_clear})

    return score, spike_index_clear, spike_index_collision
