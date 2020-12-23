#!/usr/bin/python3

import os
import random
import argparse
import rasterio

import numpy as np
import tensorflow as tf

from tensorflow.python.keras.callbacks import TensorBoard, ModelCheckpoint, \
    EarlyStopping

from data_preparation import parse_label_code, generate_dataset_structure
from cnn_lib import TrainAugmentGenerator, ValAugmentGenerator
from architectures import get_unet
from visualization import write_stats, visualize_detections


def main(data_dir, nr_epochs, batch_size, seed):
    print_device_info()

    # TODO: Make nr of bands automatically read
    generate_dataset_structure(data_dir, 12)

    label_codes, label_names, id2code = get_codings(
        data_dir + 'label_colors.txt')

    # TODO: Make nr of bands automatically read
    model = create_model(len(id2code), 12)

    # TODO: parameterize model_fn
    model_fn = '/home/ondrej/workspace/phd-pesek-2022/models/' \
               'lc_ep{}_bs{}.h5'.format(nr_epochs, batch_size)

    # TODO: parameterize train/detect
    # Train model
    train(data_dir, model, id2code, batch_size, model_fn, nr_epochs, 100,
          '/home/ondrej/workspace/phd-pesek-2022/logs',
          seed=seed, patience=100)

    # detect
    detect(data_dir, model, id2code, batch_size, [i[0] for i in label_codes],
           label_names, seed, '/tmp')


def print_device_info():
    """Print info about used GPUs."""
    print('Available GPUs:')
    print(tf.config.list_physical_devices('GPU'))

    print('Device name:')
    print(tf.random.uniform((1, 1)).device)

    print('TF executing eagerly:')
    print(tf.executing_eagerly())


def get_codings(description_file):
    """Get lists of label codes and names and a an id-name mapping dictionary.

    :param description_file: path to the txt file with labels and their names
    :return: list of label codes, list of label names, id2code dictionary
    """
    label_codes, label_names = zip(
        *[parse_label_code(i) for i in open(description_file)])
    label_codes, label_names = list(label_codes), list(label_names)
    # TODO: do I need code2id, id2name and name2id?
    code2id = {j: i for i, j in enumerate(label_codes)}
    id2code = {i: j for i, j in enumerate(label_codes)}
    name2id = {j: i for i, j in enumerate(label_names)}
    id2name = {i: j for i, j in enumerate(label_names)}

    return label_codes, label_names, id2code


def create_model(nr_classes, nr_bands, optimizer='adam',
                 loss='categorical_crossentropy', metrics=None, verbose=1):
    """Create intended model.

    So far it is only U-Net.

    :param nr_classes: number of classes to be predicted
    :param nr_bands: number of bands of intended input images
    :param optimizer: name of built-in optimizer or optimizer instance
    :param loss: name of a built-in objective function,
        objective function or tf.keras.losses.Loss instance
    :param metrics: list of metrics to be evaluated by the model during
        training and testing. Each of this can be a name of a built-in
        function, function or a tf.keras.metrics.Metric instance
    :param verbose: verbosity (0=quiet, >0 verbose)
    :return: compiled model
    """
    if metrics is None:
        metrics = ['accuracy']

    model = get_unet(nr_classes, nr_bands=nr_bands, nr_filters=32)

    # TODO: check other metrics (tversky loss, dice coef)
    model.compile(optimizer=optimizer, loss=loss, metrics=metrics)

    if verbose > 0:
        model.summary()

    return model


# TODO: support initial_epoch for fine-tuning
def train(data_dir, model, id2code, batch_size, model_fn, nr_epochs,
          nr_samples, log_dir, seed=1, patience=100):
    """Run model training.

    :param data_dir: path to the directory containing images
    :param model: model to be used for the detection
    :param id2code: dictionary mapping label ids to their codes
    :param batch_size: the number of samples that will be propagated through
        the network at once
    :param model_fn: path where the model will be saved
    :param nr_epochs: number of epochs to train the model
    :param nr_samples: sum of training and validation samples together
    :param log_dir: the path of the directory where to save the log files to
        be parsed by TensorBoard
    :param seed: the generator seed
    :param patience: number of epochs with no improvement after which training
        will be stopped
    """
    tb = TensorBoard(log_dir=log_dir, write_graph=True)
    # TODO: parameterize monitored value
    mc = ModelCheckpoint(
        mode='max', filepath=model_fn,
        monitor='val_accuracy', save_best_only='True',
        save_weights_only='True',
        verbose=1)
    es = EarlyStopping(mode='max', monitor='val_accuracy', patience=patience,
                       verbose=1, restore_best_weights=True)
    callbacks = [tb, mc, es]

    # TODO: check because of generators
    # TODO: parameterize?
    steps_per_epoch = np.ceil(float(
        nr_samples - round(0.1 * nr_samples)) / float(batch_size))
    validation_steps = (
        float((round(0.1 * nr_samples))) / float(batch_size))

    # TODO: check fit_generator()
    result = model.fit(
        TrainAugmentGenerator(data_dir, id2code, seed, batch_size),
        validation_data=ValAugmentGenerator(data_dir, id2code, seed,
                                            batch_size),
        steps_per_epoch=steps_per_epoch,
        validation_steps=validation_steps,
        epochs=nr_epochs,
        callbacks=callbacks)
    # TODO: is it needed with the model checkpoint?
    model.save_weights(model_fn, overwrite=True)

    write_stats(result, '/tmp/accu.png')


def detect(data_dir, model, id2code, batch_size, label_codes,
           label_names, seed=1, out_dir='/tmp'):
    """Run detection.

    :param data_dir: path to the directory containing images
    :param model: model to be used for the detection
    :param id2code: dictionary mapping label ids to their codes
    :param batch_size: the number of samples that will be propagated through
        the network at once
    :param label_codes: list with label codes
    :param label_names: list with label names
    :param seed: the generator seed
    :param out_dir: directory where the output visualizations will be saved
    """
    # TODO: model.load_weights()
    # TODO: Do not test on augmented data
    testing_gen = ValAugmentGenerator(data_dir, id2code, seed, batch_size)

    batch_img, batch_mask = next(testing_gen)
    pred_all = model.predict(batch_img)

    visualize_detections(batch_img, batch_mask, pred_all, id2code,
                         label_codes, label_names, out_dir)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run U-Net training and detection')

    parser.add_argument(
        '--data_dir', type=str, required=True,
        help='Path to the directory containing images and labels')
    parser.add_argument(
        '--nr_epochs', type=int, default=1,
        help='Number of epochs to train the model')
    parser.add_argument(
        '--batch_size', type=int, default=1,
        help='The number of samples that will be propagated through the '
             'network at once')
    # TODO: make seed affecting also initial weights in the model (see
    #       tf.random.set_seed)
    parser.add_argument(
        '--seed', type=int, default=1,
        help='Generator random seed')

    args = parser.parse_args()

    main(args.data_dir, args.nr_epochs, args.batch_size, args.seed)
