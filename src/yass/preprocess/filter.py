"""
Filtering functions
"""
import os
import numpy as np

from scipy.signal import butter, lfilter

from yass.batch import BatchProcessor
from yass.util import check_for_files, ExpandPath, LoadFile


@check_for_files(filenames=[ExpandPath('output_filename'),
                            LoadFile('output_filename', 'yaml')],
                 mode='extract', relative_to='output_path')
def butterworth(path_to_data, dtype, n_channels, data_order,
                low_frequency, high_factor, order, sampling_frequency,
                max_memory, output_path, output_dtype,
                output_filename='filtered.bin', if_file_exists='skip'):
    """Filter (butterworth) recordings in batches

    Parameters
    ----------
    path_to_data: str
        Path to recordings in binary format

    dtype: str
        Recordings dtype

    n_channels: int
        Number of channels in the recordings

    data_order: str
        Recordings order, one of ('channels', 'samples'). In a dataset with k
        observations per channel and j channels: 'channels' means first k
        contiguous observations come from channel 0, then channel 1, and so
        on. 'sample' means first j contiguous data are the first observations
        from all channels, then the second observations from all channels and
        so on

    low_frequency: int
        Low pass frequency (Hz)

    high_factor: float
        High pass factor (proportion of sampling rate)

    order: int
        Order of Butterworth filter

    sampling_frequency: int
        Recordings sampling frequency in Hz

    max_memory: str
        Max memory to use in each batch (e.g. 100MB, 1GB)

    output_path: str
        Folder to store the filtered recordings

    output_filename: str, optional
        How to name the file, defaults to filtered.bin

    output_dtype: str
        dtype for filtered data

    if_file_exists: str, optional
        One of 'overwrite', 'abort', 'skip'. If 'overwrite' it replaces the
        file if it exists, if 'abort' if raise a ValueError exception if
        the file exists, if 'skip' if skips the operation if the file
        exists

    Returns
    -------
    standarized_path: str
        Location to filtered recordings

    standarized_params: dict
        A dictionary with the parameters for the filtered recordings
        (dtype, n_channels, data_order)
    """
    # init batch processor
    bp = BatchProcessor(path_to_data, dtype, n_channels, data_order,
                        max_memory, buffer_size=200)

    _output_path = os.path.join(output_path, output_filename)

    (path,
     params) = bp.multi_channel_apply(_butterworth, mode='disk',
                                      cleanup_function=fix_indexes,
                                      output_path=_output_path,
                                      if_file_exists=if_file_exists,
                                      cast_dtype=output_dtype,
                                      low_frequency=low_frequency,
                                      high_factor=high_factor,
                                      order=order,
                                      sampling_frequency=sampling_frequency)

    return path, params


def _butterworth(ts, low_frequency, high_factor, order, sampling_frequency):
    """Butterworth filter for a one dimensional time series

    Parameters
    ----------
    ts: np.array
        T  numpy array, where T is the number of time samples
    low_frequency: int
        Low pass frequency (Hz)
    high_factor: float
        High pass factor (proportion of sampling rate)
    order: int
        Order of Butterworth filter
    sampling_frequency: int
        Sampling frequency (Hz)

    Notes
    -----
    This function can only be applied to a one dimensional array, to apply
    it to multiple channels use butterworth

    Raises
    ------
    NotImplementedError
        If a multidmensional array is passed
    """

    if ts.ndim == 1:

        (T,) = ts.shape
        low = float(low_frequency)/sampling_frequency * 2
        high = float(high_factor) * 2
        b, a = butter(order, [low, high], btype='band')

        return lfilter(b, a, ts)

    else:

        T, C = ts.shape
        low = float(low_frequency)/sampling_frequency * 2
        high = float(high_factor) * 2
        b, a = butter(order, [low, high], btype='band')

        output = np.zeros((T, C), 'float32')
        for c in range(C):
            output[:, c] = lfilter(b, a, ts[:, c])

        return output


def fix_indexes(res, idx_local, idx, buffer_size):
    """Fixes indexes from detected spikes in batches

    Parameters
    ----------
    res: tuple
        A result from the butterworth
    idx_local: slice
        A slice object indicating the indices for the data (excluding buffer)
    idx: slice
        A slice object indicating the absolute location of the data
    buffer_size: int
        Buffer size
    """

    # get limits for the data (exlude indexes that have buffer data)
    data_start = idx_local[0].start
    data_end = idx_local[0].stop

    return res[data_start:data_end]
