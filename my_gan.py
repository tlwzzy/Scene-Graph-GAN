import os, sys
sys.path.append(os.getcwd())

import time
import json
import random

import numpy as np
import tensorflow as tf

import tflib as lib
import tflib.ops.linear
import tflib.ops.conv1d
import tflib.plot

from tqdm import tqdm
from generator import Generator
from discriminator import Discriminator
from subprocess import call


class SceneGraphWGAN(object):
    def __init__(self, batch_path, path_to_vocab_json, BATCH_SIZE=64):
        self.batch_path = batch_path
        self.batch_path += "/" if self.batch_path[-1] != "/" else ""
        self.path_to_vocab_json = path_to_vocab_json
        self.path_to_vocab_json += "/" if self.path_to_vocab_json != "/" else ""
        self.logs_dir = "./logs/"
        self.checkpoints_dir = os.path.join(self.logs_dir, "checkpoints/")
        self.summaries_dir = os.path.join(self.logs_dir, "summaries/")

        if not os.path.exists(self.checkpoints_dir):
            os.makedirs(self.checkpoints_dir)

        if not os.path.exists(self.summaries_dir):
            os.makedirs(self.summaries_dir)

        
        call(["rm", "{}*".format(self.summaries_dir)])

        #Calculating vocabulary and sequence lengths
        with open(path_to_vocab_json, "r") as f:
            self.vocab = json.load(f)
        self.vocab_size = len(self.vocab)
        self.decoder = {y[0]:x for x, y in self.vocab.iteritems()}
        self.seq_len = 3

        #Image feature dimensionality
        self.image_feat_dim = [196, 512]

        #Hyperparameters
        self.BATCH_SIZE = BATCH_SIZE
        self.LAMBDA = 10
        self.CRITIC_ITERS = 25
        self.DIM = 512
        self.ITERS = 100000

        #Initialize all the generator and discriminator variables
        with tf.variable_scope("Generator") as scope:
            self.g = Generator(self.vocab_size, n_lstm_steps = self.seq_len, batch_size = self.BATCH_SIZE)

        with tf.variable_scope("Discriminator") as scope:
            self.d = Discriminator(self.vocab_size, batch_size = self.BATCH_SIZE)

    def softmax(self, logits):
        return tf.reshape(
            tf.nn.softmax(
                tf.reshape(logits, [-1, self.vocab_size])
            ),
            tf.shape(logits)
        )

    def make_noise(self, shape):
        return tf.random_normal(shape)

    def ResBlock(self, name, inputs):
        output = inputs
        output = tf.nn.relu(output)
        output = lib.ops.conv1d.Conv1D(name+'.1', self.DIM, self.DIM, 5, output)
        output = tf.nn.relu(output)
        output = lib.ops.conv1d.Conv1D(name+'.2', self.DIM, self.DIM, 5, output)
        return inputs + (0.3*output)

    def Generator(self, n_samples, image_feats, prev_outputs=None):
        #noise_dim = 128
        #output = self.make_noise(shape=[n_samples, noise_dim])
        #output = lib.ops.linear.Linear('Generator.Input', noise_dim, self.seq_len*self.DIM, output)
        #output = tf.reshape(output, [-1, self.DIM, self.seq_len])
        #output = self.ResBlock('Generator.1', output)
        #output = self.ResBlock('Generator.2', output)
        #output = self.ResBlock('Generator.3', output)
        #output = self.ResBlock('Generator.4', output)
        #output = self.ResBlock('Generator.5', output)
        #output = lib.ops.conv1d.Conv1D('Generator.Output', self.DIM, self.vocab_size, 1, output)
        #output = tf.transpose(output, [0, 2, 1])
        #output = self.softmax(output)
        #return output
        with tf.variable_scope("Generator", reuse=True) as scope:
            #g = Generator(self.vocab_size, n_lstm_steps = self.seq_len, batch_size = self.BATCH_SIZE)
            generated_words = self.g.build_generator(image_feats)
            return generated_words

    def Discriminator(self, triple_input, image_feats):
        #output = tf.transpose(triple_input, [0,2,1])
        #output = lib.ops.conv1d.Conv1D('Discriminator.Input', self.vocab_size, self.DIM, 1, output)
        #output = self.ResBlock('Discriminator.1', output)
        #output = self.ResBlock('Discriminator.2', output)
        #output = self.ResBlock('Discriminator.3', output)
        #output = self.ResBlock('Discriminator.4', output)
        #output = self.ResBlock('Discriminator.5', output)
        #output = tf.reshape(output, [-1, self.seq_len*self.DIM])
        #output = lib.ops.linear.Linear('Discriminator.Output', self.seq_len*self.DIM, 1, output)
        #return output
        with tf.variable_scope("Discriminator", reuse=True) as scope:
            logits = self.d.build_discriminator(image_feats, triple_input)
            return logits

    def Loss(self):
        #real_inputs_discrete = tf.placeholder(tf.int32, shape=[self.BATCH_SIZE, self.seq_len])
        #real_inputs = tf.one_hot(real_inputs_discrete, len(charmap))
        self.real_inputs = tf.placeholder(tf.float32, shape=[None, self.seq_len, self.vocab_size])
        self.image_feats = tf.placeholder(tf.float32, shape=[None, self.image_feat_dim[0], self.image_feat_dim[1]])
        fake_inputs = self.Generator(self.BATCH_SIZE, self.image_feats)
        fake_inputs_discrete = tf.argmax(fake_inputs, fake_inputs.get_shape().ndims-1)

        self.fake_inputs = fake_inputs

        disc_real = self.Discriminator(self.real_inputs, self.image_feats) 
        disc_fake = self.Discriminator(fake_inputs, self.image_feats)

        disc_cost = tf.reduce_mean(disc_fake) - tf.reduce_mean(disc_real)
        gen_cost = -tf.reduce_mean(disc_fake)

        tf.summary.scalar("Discriminator Cost", disc_cost)
        tf.summary.scalar("Generator Cost", gen_cost)

        # WGAN lipschitz-penalty
        alpha = tf.random_uniform(
            shape=[self.BATCH_SIZE,1,1], 
            minval=0.,
            maxval=1.
        )
        differences = fake_inputs - self.real_inputs
        interpolates = self.real_inputs + (alpha*differences)
        gradients = tf.gradients(self.Discriminator(interpolates, self.image_feats), [interpolates])[0]
        slopes = tf.sqrt(tf.reduce_sum(tf.square(gradients), reduction_indices=[1,2]))
        gradient_penalty = tf.reduce_mean((slopes-1.)**2)
        disc_cost += self.LAMBDA*gradient_penalty

        self.disc_cost = disc_cost
        self.gen_cost = gen_cost

        train_variables = tf.trainable_variables()
        gen_params = [v for v in train_variables if v.name.startswith("Generator")]
        disc_params = [v for v in train_variables if v.name.startswith("Discriminator")]

        optimizer = tf.train.AdamOptimizer(learning_rate=1e-4, beta1=0.5, beta2=0.9)

        gen_grads = optimizer.compute_gradients(gen_cost, var_list=gen_params)
        disc_grads = optimizer.compute_gradients(disc_cost, var_list=disc_params)

        #self.gen_train_op = tf.train.AdamOptimizer(learning_rate=1e-4, beta1=0.5, beta2=0.9).minimize(gen_cost, var_list=gen_params)
        #self.disc_train_op = tf.train.AdamOptimizer(learning_rate=1e-4, beta1=0.5, beta2=0.9).minimize(disc_cost, var_list=disc_params)

        self.gen_train_op = optimizer.apply_gradients(gen_grads)
        self.disc_train_op = optimizer.apply_gradients(disc_grads)

        for grad, var in gen_grads:
            if grad is not None:
                tf.summary.histogram(var.op.name + "/gradient", grad)

        for grad, var in disc_grads:
            if grad is not None:
                tf.summary.histogram(var.op.name + "/gradient", grad)

    def DataGenerator(self):
        filenames = ["{}{}".format(self.batch_path, i) for i in os.listdir(self.batch_path)]
        for f in filenames:
            npz = np.load(f)
            big_arr = npz['arr_0']
            all_pairs = []
            for i in xrange(0, big_arr.shape[0], 2):
                im_feats = big_arr[i]
                caps = big_arr[i+1]
                for c in xrange(caps.shape[0]):
                    all_pairs.append((im_feats, caps[c]))
            indices = list(range(len(all_pairs)))
            random.shuffle(indices)
            while len(indices) > self.BATCH_SIZE:
                im_batch = np.array([all_pairs[i][0] for i in indices[-self.BATCH_SIZE:]], dtype=np.float32)
                triple_batch = np.array([all_pairs[i][1] for i in indices[-self.BATCH_SIZE:]])
                t_batch = np.zeros((self.BATCH_SIZE, 3, self.vocab_size), dtype=np.float32)
                for row in range(t_batch.shape[0]):
                    for token in range(t_batch.shape[1]):
                        t_batch[row, token, triple_batch[row, token]] = 1.0
                del indices[-self.BATCH_SIZE:]
                yield im_batch, t_batch

    """def generateSamples(self, session):
        #Load features from a specific image
        ##Load the image
        path_to_image = "/home/mklawonn/visual_genome/all_images/0.jpg"
        ##Extract features
        ##Load the image in a tensor
        #Generate triples from this image
        
        #Write a summary that puts the image and ground truth in tensorboard
        #Write a summary that puts generated triples into tensorboard"""


    def Train(self, epochs):
        self.saver = tf.train.Saver()
        self.Loss()
        summary_op = tf.summary.merge_all()
        start_time = time.time()
        with tf.Session() as session:
            #self.generateSamples(session)
            writer = tf.summary.FileWriter(self.summaries_dir, session.graph)


            session.run(tf.global_variables_initializer())

            def generate_samples(image_feats):
                samples = session.run(self.fake_inputs, feed_dict={self.image_feats: image_feats})
                samples = np.argmax(samples, axis=2)
                decoded_samples = []
                for i in xrange(len(samples)):
                    decoded = []
                    for j in xrange(len(samples[i])):
                        decoded.append(self.decoder[samples[i][j]])
                    decoded_samples.append(tuple(decoded))
                return decoded_samples

            gen = self.DataGenerator()

            for epoch in range(epochs):
                iteration = 0
                for im_batch, triple_batch in self.DataGenerator():
                    #Train Generator
                    if iteration > 0:
                        _ = session.run(self.gen_train_op, feed_dict={self.image_feats:im_batch})

                    #Train Critic
                    for i in xrange(self.CRITIC_ITERS):
                        #im_batch, triple_batch = gen.next()
                        _disc_cost, _ = session.run(
                            [self.disc_cost, self.disc_train_op],
                            feed_dict={self.real_inputs:triple_batch, self.image_feats:im_batch}
                        )

                    if iteration % 5 == 0:

                        """stop_time = time.time()
                        duration = (stop_time - start_time) / 200.0
                        start_time = stop_time"""
                        summary, _gen_cost = session.run([summary_op, self.gen_cost], feed_dict={self.real_inputs:triple_batch, self.image_feats:im_batch})
                        writer.add_summary(summary, iteration)
                        writer.flush()

                        """print "Time {}/itr, Step: {}, generator loss: {}, discriminator loss: {}".format(
                                duration, iteration, _gen_cost, _disc_cost)"""

                    if iteration % 25 == 0:
                        samples = []
                        for i in xrange(10):
                            samples.extend(generate_samples(im_batch))

                        with open('./samples/samples_{}.txt'.format(iteration), 'w') as f:
                            for s in samples:
                                s = " ".join(s)
                                f.write(s + "\n")

                        
                        self.saver.save(session, os.path.join(self.checkpoints_dir, "model.ckpt"), global_step=(epoch+1)*iteration)
                    iteration += 1


if __name__ == "__main__":
    arg_dict = {}
    with open("./config.txt", "r") as f:
        for line in f:
            line_ = line.split()
            arg_dict[line_[0]] = line_[1]
    batch_path = "{}{}".format(arg_dict["visual_genome"], "batches")
    path_to_vocab_json = arg_dict["vocab"]
    logs_dir = arg_dict["logs"]
    BATCH_SIZE = 64
    wgan = SceneGraphWGAN(batch_path, path_to_vocab_json, BATCH_SIZE=BATCH_SIZE)
    #wgan.create_network()
    #wgan.initialize_network(logs_dir)
    #wgan.train_model(25)
    wgan.Train(32)
