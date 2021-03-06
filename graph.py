from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf

from tensorflow.contrib import rnn

import pdb


class Shared_Model(object):
    """Tensorflow Graph For Shared Pos & Chunk Model"""

    def __init__(self, config, is_training):
        self.max_grad_norm = config.max_grad_norm
        self.num_steps = num_steps = config.num_steps
        self.encoder_size = config.encoder_size
        self.pos_decoder_size = config.pos_decoder_size
        self.chunk_decoder_size = config.chunk_decoder_size
        self.batch_size = config.batch_size
        self.vocab_size = config.vocab_size
        self.num_pos_tags = config.num_pos_tags
        self.num_chunk_tags = config.num_chunk_tags
        self.input_data = tf.placeholder(tf.int32, [config.batch_size, num_steps])
        self.word_embedding_size = config.word_embedding_size
        self.pos_embedding_size = config.pos_embedding_size
        self.num_shared_layers = config.num_shared_layers
        self.argmax = config.argmax

        # add input size - size of pos tags
        self.pos_targets = tf.placeholder(tf.float32, [(self.batch_size * num_steps),
                                                       self.num_pos_tags])
        self.chunk_targets = tf.placeholder(tf.float32, [(self.batch_size * num_steps),
                                                         self.num_chunk_tags])

        self._build_graph(config, is_training)

    def _shared_layer(self, input_data, config, is_training):
        """Build the model up until decoding.

        Args:
            input_data = size batch_size X num_steps X embedding size

        Returns:
            output units
        """

        with tf.variable_scope('encoder'):
            lstm_cell = rnn.BasicLSTMCell(config.encoder_size, reuse=tf.get_variable_scope().reuse, forget_bias=1.0)
            if is_training and config.keep_prob < 1:
                lstm_cell = rnn.DropoutWrapper(
                    lstm_cell, output_keep_prob=config.keep_prob)
            encoder_outputs, encoder_states = tf.nn.dynamic_rnn(lstm_cell,
                                                                input_data,
                                                                dtype=tf.float32,
                                                                scope="encoder_rnn")

        return encoder_outputs

    def _pos_private(self, encoder_units, config, is_training):
        """Decode model for pos

        Args:
            encoder_units - these are the encoder units
            num_pos - the number of pos tags there are (output units)

        returns:
            logits
        """
        with tf.variable_scope("pos_decoder"):
            pos_decoder_cell = rnn.BasicLSTMCell(config.pos_decoder_size,
                                     forget_bias=1.0, reuse=tf.get_variable_scope().reuse)

            if is_training and config.keep_prob < 1:
                pos_decoder_cell = rnn.DropoutWrapper(
                    pos_decoder_cell, output_keep_prob=config.keep_prob)

            encoder_units = tf.transpose(encoder_units, [1, 0, 2])

            decoder_outputs, decoder_states = tf.nn.dynamic_rnn(pos_decoder_cell,
                                                                encoder_units,
                                                                dtype=tf.float32,
                                                                scope="pos_rnn")

            output = tf.reshape(tf.concat(decoder_outputs, 1),
                                [-1, config.pos_decoder_size])

            softmax_w = tf.get_variable("softmax_w",
                                        [config.pos_decoder_size,
                                         config.num_pos_tags])
            softmax_b = tf.get_variable("softmax_b", [config.num_pos_tags])
            logits = tf.matmul(output, softmax_w) + softmax_b

        return logits, decoder_states

    def _chunk_private(self, encoder_units, pos_prediction, config, is_training):
        """Decode model for chunks

        Args:
            encoder_units - these are the encoder units:
            [batch_size X encoder_size] with the one the pos prediction
            pos_prediction:
            must be the same size as the encoder_size

        returns:
            logits
        """
        # concatenate the encoder_units and the pos_prediction

        pos_prediction = tf.reshape(pos_prediction,
                                    [self.batch_size, self.num_steps, self.pos_embedding_size])
        encoder_units = tf.transpose(encoder_units, [1, 0, 2])
        chunk_inputs = tf.concat([pos_prediction, encoder_units], 2)

        with tf.variable_scope("chunk_decoder"):
            cell = rnn.BasicLSTMCell(config.chunk_decoder_size, forget_bias=1.0, reuse=tf.get_variable_scope().reuse)

            if is_training and config.keep_prob < 1:
                cell = rnn.DropoutWrapper(
                    cell, output_keep_prob=config.keep_prob)

            decoder_outputs, decoder_states = tf.nn.dynamic_rnn(cell,
                                                                chunk_inputs,
                                                                dtype=tf.float32,
                                                                scope="chunk_rnn")

            output = tf.reshape(tf.concat(decoder_outputs, 1),
                                [-1, config.chunk_decoder_size])

            softmax_w = tf.get_variable("softmax_w",
                                        [config.chunk_decoder_size,
                                         config.num_chunk_tags])
            softmax_b = tf.get_variable("softmax_b", [config.num_chunk_tags])
            logits = tf.matmul(output, softmax_w) + softmax_b

        return logits, decoder_states

    def _loss(self, logits, labels):
        """Calculate loss for both pos and chunk
            Args:
                logits from the decoder
                labels - one-hot
            returns:
                loss as tensor of type float
        """
        cross_entropy = tf.nn.softmax_cross_entropy_with_logits(logits=logits,
                                                                labels=labels,
                                                                name='xentropy')
        loss = tf.reduce_mean(cross_entropy, name='xentropy_mean')
        (_, int_targets) = tf.nn.top_k(labels, 1)
        (_, int_predictions) = tf.nn.top_k(logits, 1)
        num_true = tf.reduce_sum(tf.cast(tf.equal(int_targets, int_predictions), tf.float32))
        accuracy = num_true / (self.num_steps * self.batch_size)
        return loss, accuracy, int_predictions, int_targets

    def _training(self, loss, config):
        """Sets up training ops

        Creates the optimiser

        The op returned from this is what is passed to session run

            Args:
                loss float
                learning_rate float

            returns:

            Op for training
        """
        # Create the gradient descent optimizer with the
        # given learning rate.
        tvars = tf.trainable_variables()
        grads, _ = tf.clip_by_global_norm(tf.gradients(loss, tvars),
                                          config.max_grad_norm)
        optimizer = tf.train.AdamOptimizer()
        train_op = optimizer.apply_gradients(zip(grads, tvars))
        return train_op

    def _build_graph(self, config, is_training):
        word_embedding = tf.get_variable("word_embedding", [config.vocab_size, config.word_embedding_size])
        inputs = tf.nn.embedding_lookup(word_embedding, self.input_data)
        pos_embedding = tf.get_variable("pos_embedding", [config.num_pos_tags, config.pos_embedding_size])

        if is_training and config.keep_prob < 1:
            inputs = tf.nn.dropout(inputs, config.keep_prob)

        encoding = self._shared_layer(inputs, config, is_training)

        encoding = tf.stack(encoding)
        encoding = tf.transpose(encoding, perm=[1, 0, 2])

        pos_logits, pos_states = self._pos_private(encoding, config, is_training)
        pos_loss, pos_accuracy, pos_int_pred, pos_int_targ = self._loss(pos_logits, self.pos_targets)
        self.pos_loss = pos_loss

        self.pos_int_pred = pos_int_pred
        self.pos_int_targ = pos_int_targ

        # choose either argmax or dot product for pos
        if config.argmax == 1:
            pos_to_chunk_embed = tf.nn.embedding_lookup(pos_embedding, pos_int_pred)
        else:
            pos_to_chunk_embed = tf.matmul(tf.nn.softmax(pos_logits), pos_embedding)

        chunk_logits, chunk_states = self._chunk_private(encoding, pos_to_chunk_embed, config, is_training)
        chunk_loss, chunk_accuracy, chunk_int_pred, chunk_int_targ = self._loss(chunk_logits, self.chunk_targets)
        self.chunk_loss = chunk_loss

        self.chunk_int_pred = chunk_int_pred
        self.chunk_int_targ = chunk_int_targ
        self.joint_loss = chunk_loss + pos_loss

        # return pos embedding
        self.pos_embedding = pos_embedding

        if not is_training:
            return

        self.pos_op = self._training(pos_loss, config)
        self.chunk_op = self._training(chunk_loss, config)
        self.joint_op = self._training(chunk_loss + pos_loss, config)
