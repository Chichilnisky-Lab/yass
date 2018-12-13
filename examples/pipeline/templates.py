import numpy as np
import logging

import yass
from yass import preprocess
from yass import detect
from yass import cluster
from yass import templates

np.random.seed(0)

# configure logging module to get useful information
logging.basicConfig(level=logging.INFO)

# set yass configuration parameters
yass.set_config('config_sample.yaml', 'templates-example')

standardized_path, standardized_params, whiten_filter = preprocess.run()

(spike_index_clear,
 spike_index_all) = detect.run(standardized_path,
                               standardized_params,
                               whiten_filter)


spike_train_clear, tmp_loc, vbParam = cluster.run(spike_index_clear)

(templates_, spike_train,
 groups, idx_good_templates) = templates.run(
    spike_train_clear, tmp_loc)
