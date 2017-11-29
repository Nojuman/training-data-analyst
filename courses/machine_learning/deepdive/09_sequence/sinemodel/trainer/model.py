#!/usr/bin/env python

# Copyright 2017 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import shutil
import tensorflow.contrib.learn as learn
import tensorflow.contrib.layers as tflayers
from tensorflow.contrib.learn.python.learn import learn_runner
import tensorflow.contrib.metrics as metrics
import tensorflow.contrib.rnn as rnn

tf.logging.set_verbosity(tf.logging.INFO)

TIMESERIES_COL = 'rawdata'
N_OUTPUTS = 1  # in each sequence, 1-9 are features, and 10 is label
SEQ_LEN = None
DEFAULTS = None
N_INPUTS = None

def init(hparams):
  global SEQ_LEN, DEFAULTS, N_INPUTS
  SEQ_LEN =  hparams['sequence_length']
  DEFAULTS = [[0.0] for x in xrange(0, SEQ_LEN)]
  N_INPUTS = SEQ_LEN - N_OUTPUTS

# read data and convert to needed format
def read_dataset(filename, mode, batch_size):  
  def _input_fn():
    # could be a path to one file or a file pattern.
    input_file_names = tf.train.match_filenames_once(filename)
    filename_queue = tf.train.string_input_producer(
        input_file_names, num_epochs=None, shuffle=True)

    reader = tf.TextLineReader()
    _, value = reader.read_up_to(filename_queue, num_records=batch_size)

    value_column = tf.expand_dims(value, -1)
    #print ('readcsv={}'.format(value_column))
    
    # all_data is a list of tensors
    all_data = tf.decode_csv(value_column, record_defaults=DEFAULTS)  
    inputs = all_data[:len(all_data)-N_OUTPUTS]  # first few values
    label = all_data[len(all_data)-N_OUTPUTS : ] # last few values
    
    # from list of tensors to tensor with one more dimension
    inputs = tf.concat(inputs, axis=1)
    label = tf.concat(label, axis=1)
    #print ('inputs={}'.format(inputs))
    
    return {TIMESERIES_COL: inputs}, label   # dict of features, label
  return _input_fn

# create the inference model
def dnn_model(features, mode, params):
  X = tf.reshape(features[TIMESERIES_COL], [-1, N_INPUTS]) # flattened
  h1 = tf.layers.dense(X, 10, activation=tf.nn.relu)
  h2 = tf.layers.dense(h1, 3, activation=tf.nn.relu)
  predictions = tf.layers.dense(h2, 1, activation=None) # linear output: regression
  return predictions

def cnn_model(features, mode, params):
  X = tf.reshape(features[TIMESERIES_COL], [-1, N_INPUTS, 1]) # as a 1D "image" with a grayscale channel ?x10x1
  c1 = tf.layers.max_pooling1d(
         tf.layers.conv1d(X, filters=N_INPUTS//2,
                          kernel_size=3, strides=1, # ?x10x5
                          padding='same', activation=tf.nn.relu),
         pool_size=2, strides=2
       ) # ?x5x5
  c2 = tf.layers.max_pooling1d(
         tf.layers.conv1d(c1, filters=N_INPUTS//2,
                          kernel_size=3, strides=1,
                          padding='same', activation=tf.nn.relu),
         pool_size=2, strides=2
       ) # ?x2x5
  outlen = (N_INPUTS//4) * (N_INPUTS//2)
  c2flat = tf.reshape(c2, [-1, outlen])
  h1 = tf.layers.dense(c2flat, 3, activation=tf.nn.relu)
  predictions = tf.layers.dense(h1, 1, activation=None) # linear output: regression
  return predictions

def lstm_model(features, mode, params):
  LSTM_SIZE = 3  # number of hidden layers in each of the LSTM cells

  # 1. Reformat input shape to become a sequence
  x = tf.split(features[TIMESERIES_COL], N_INPUTS, 1)
    
  # 2. configure the RNN
  lstm_cell = rnn.BasicLSTMCell(LSTM_SIZE, forget_bias=1.0)
  outputs, _ = rnn.static_rnn(lstm_cell, x, dtype=tf.float32)

  # 3. slice to keep only the last cell of the RNN
  outputs = outputs[-1]
  
  # 4. output is result of linear activation of last layer of RNN
  weight = tf.Variable(tf.random_normal([LSTM_SIZE, N_OUTPUTS]))
  bias = tf.Variable(tf.random_normal([N_OUTPUTS]))
  predictions = tf.matmul(outputs, weight) + bias
  
  return predictions

def lstm2_model(features, mode, params):
  LSTM_SIZE = N_INPUTS//3  # number of hidden layers in each of the LSTM cells

  # 1. Reformat input shape to become a sequence
  x = tf.split(features[TIMESERIES_COL], N_INPUTS, 1)
    
  # 2. configure the RNN
  lstm_cell = rnn.BasicLSTMCell(LSTM_SIZE, forget_bias=1.0)
  outputs, _ = rnn.static_rnn(lstm_cell, x, dtype=tf.float32)

  # 3. flatten lstm output and pass through a dense layer
  lstm_flat = tf.reshape(outputs, [-1, lstm_cell.output_size*N_INPUTS])
  h1 = tf.layers.dense(lstm_flat, N_INPUTS//2, activation=tf.nn.relu)
  predictions = tf.layers.dense(h1, 1, activation=None) # (?, 1)
  return predictions

 
def serving_input_fn():
    feature_placeholders = {
        TIMESERIES_COL: tf.placeholder(tf.float32, [None, N_INPUTS])
    }
  
    features = {
      key: tf.expand_dims(tensor, -1)
      for key, tensor in feature_placeholders.items()
    }
    features[TIMESERIES_COL] = tf.squeeze(features[TIMESERIES_COL], axis=[2])

    return tf.estimator.export.ServingInputReceiver(features, feature_placeholders)