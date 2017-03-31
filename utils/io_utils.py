"""Utilities for downloading data from various datasets, tokenizing, vocabularies."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import re
import sys
import yaml
import pandas as pd

import numpy as np
import tensorflow as tf
from tensorflow.python.platform import gfile
from collections import Counter


# Special vocabulary symbols.
_PAD = b"_PAD"      # Append to unused space for both encoder/decoder.
_GO  = b"_GO"       # Prepend to each decoder input.
_EOS = b"_EOS"      # Append to outputs only. Stopping signal when decoding.
_UNK = b"_UNK"      # For any symbols not in our vocabulary.
_START_VOCAB = [_PAD, _GO, _EOS, _UNK]

# Enumerations for ease of use by this and other files.
PAD_ID  = 0
GO_ID   = 1
EOS_ID  = 2
UNK_ID  = 3

# Regular expressions used to tokenize.
_WORD_SPLIT = re.compile(b"([.,!?\"':;)(])")
_DIGIT_RE   = re.compile(br"\d")

utils_dir = os.path.dirname(os.path.realpath(__file__))


def save_hyper_params(hyper_params, fname):
    # Append to file if exists, else create.
    df = pd.DataFrame(hyper_params)
    with open(fname, 'a+') as f:
        df.to_csv(f, header=False)


def get_sentence():
    """Simple function to prompt user for input and return it w/o newline.
    Frequently used in chat sessions, of course.
    """
    sys.stdout.write("Human: ")
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower() # Could just use input() ...


def yaml_to_dict(config_path):
    """
    Args:
        config_path: (str) location of [my config].yml file, relative to project root.

    Returns:
        configs: dictionary of (hyper)parameters for models/directories.
    """
    config_path = os.path.join(utils_dir, '../configs', os.path.basename(config_path))
    with tf.gfile.GFile(config_path) as config_file:
        configs = yaml.load(config_file)
    return configs


def flags_to_dict(flags):
    """Builds and return a dictionary from flags keys, namely
       'model', 'dataset', 'model_params', 'dataset_params'.
    """
    flags_dict = {}
    for stream in ['model', 'dataset', 'model_params', 'dataset_params']:
        yaml_stream = yaml.load(flags.__dict__['__flags'][stream])
        if yaml_stream:
            flags_dict.update({stream: yaml_stream})
    return flags_dict


def parse_config(flags):
    """Get configuration information from FLAGS, namely:
        1. any configuration file (.yml) paths.
        2. any dictionaries defined by user at command-line.

    Args:
        flags: tf.app.flags instance. Assumes supports keys from main, namely
                model, dataset, model_params, dataset_params.

    Returns:
        merged dictionary of config info, where precedence is given to user-specified
        params on command-line (over .yml config files).
    """

    yaml_config = yaml_to_dict(flags.config)
    flags_dict = flags_to_dict(flags)
    #return {**yaml_config, **flags_dict}
    merged_dict = dict()
    for key in yaml_config:
        if isinstance(yaml_config[key], dict):
            if key in flags_dict:
                merged_dict.update(
                    {key: {**yaml_config[key], **flags_dict[key]}})
            else:
                merged_dict.update(
                    {key: yaml_config[key]})
        else:
            merged_dict.update({key: yaml_config[key]})
        print(merged_dict)
    return merged_dict


def basic_tokenizer(sentence):
    """Very basic tokenizer: split the sentence into a list of tokens."""
    words = []
    for space_separated_fragment in sentence.strip().split():
        words.extend(_WORD_SPLIT.split(space_separated_fragment))
    return [w for w in words if w]


def create_vocabulary(vocabulary_path, data_path, max_vocabulary_size, normalize_digits=True):
    """Create vocabulary file (if it does not exist yet) from data file.

    Data file is assumed to contain one sentence per line. Each sentence is
    tokenized and digits are normalized (if normalize_digits is set).
    Vocabulary contains the most-frequent tokens up to max_vocabulary_size.
    We write it to vocabulary_path in a one-token-per-line format, so that later
    token in the first line gets id=0, second line gets id=1, and so on.

    Args:
      vocabulary_path: path where the vocabulary will be created.
      data_path: data file that will be used to create vocabulary.
      max_vocabulary_size: limit on the size of the created vocabulary.
      tokenizer: a function to use to tokenize each data sentence;
        if None, basic_tokenizer will be used.
      normalize_digits: Boolean; if true, all digits are replaced by 0s.
    """

    if gfile.Exists(vocabulary_path): return

    print("Creating vocabulary %s from data %s" % (vocabulary_path, data_path))
    vocab = Counter()
    with gfile.GFile(data_path, mode="rb") as f:
        counter = 0
        for line in f:
            counter += 1
            if counter % 100000 == 0:
                print("  processing line %d" % counter)

            line   = tf.compat.as_bytes(line)
            tokens = basic_tokenizer(line)
            # Update word frequency counts in vocab counter dict.
            for w in tokens:
                word = _DIGIT_RE.sub(b"0", w) if normalize_digits else w
                vocab[word] += 1

        # Get sorted vocabulary, from most frequent to least frequent.
        vocab_list = _START_VOCAB + sorted(vocab, key=vocab.get, reverse=True)
        vocab_list = vocab_list[:max_vocabulary_size]

        # Write the list to a file.
        with gfile.GFile(vocabulary_path, mode="wb") as vocab_file:
            for w in vocab_list:
                vocab_file.write(w + b"\n")


def get_vocab_dicts(vocabulary_path):
    """Returns word_to_idx, idx_to_word dictionaries given vocabulary.

    Args:
      vocabulary_path: path to the file containing the vocabulary.

    Returns:
      a pair: the vocabulary (a dictionary mapping string to integers), and
      the reversed vocabulary (a list, which reverses the vocabulary mapping).

    Raises:
      ValueError: if the provided vocabulary_path does not exist.
    """
    if gfile.Exists(vocabulary_path):
        rev_vocab = []
        with gfile.GFile(vocabulary_path, mode="rb") as f:
            rev_vocab.extend(f.readlines())
        rev_vocab = [tf.compat.as_bytes(line.strip()) for line in rev_vocab]
        vocab = dict([(x, y) for (y, x) in enumerate(rev_vocab)])
        return vocab, rev_vocab
    else:
        raise ValueError("Vocabulary file %s not found.", vocabulary_path)


def sentence_to_token_ids(sentence, vocabulary, normalize_digits=True):
    """Convert a string to list of integers representing token-ids.

    For example, a sentence "I have a dog" may become tokenized into
    ["I", "have", "a", "dog"] and with vocabulary {"I": 1, "have": 2,
    "a": 4, "dog": 7"} this function will return [1, 2, 4, 7].

    Args:
      sentence: the sentence in bytes format to convert to token-ids.
      vocabulary: a dictionary mapping tokens to integers.
      normalize_digits: Boolean; if true, all digits are replaced by 0s.

    Returns:
      a list of integers, the token-ids for the sentence.
    """
    words = basic_tokenizer(sentence)

    if not normalize_digits:
        return [vocabulary.get(w, UNK_ID) for w in words]

    # Normalize digits by 0 before looking words up in the vocabulary.
    return [vocabulary.get(_DIGIT_RE.sub(b"0", w), UNK_ID) for w in words]


def data_to_token_ids(data_path, target_path, vocabulary_path, normalize_digits=True):
    """Tokenize data file and turn into token-ids using given vocabulary file.

    This function loads data line-by-line from data_path, calls the above
    sentence_to_token_ids, and saves the result to target_path.

    Args:
      data_path: path to the data file in one-sentence-per-line format.
      target_path: path where the file with token-ids will be created.
      vocabulary_path: path to the vocabulary file.
      normalize_digits: Boolean; if true, all digits are replaced by 0s.
    """
    if not gfile.Exists(target_path):
        print("Tokenizing data in %s" % data_path)
        vocab, _ = get_vocab_dicts(vocabulary_path)
        with gfile.GFile(data_path, mode="rb") as data_file:
            with gfile.GFile(target_path, mode="w") as tokens_file:
                counter = 0
                for line in data_file:
                    counter += 1
                    if counter % 100000 == 0:
                        print("  tokenizing line %d" % counter)
                    token_ids = sentence_to_token_ids(tf.compat.as_bytes(line),
                                                      vocab,
                                                      normalize_digits)
                    tokens_file.write(" ".join([str(tok) for tok in token_ids]) + "\n")


def prepare_data(data_dir, from_train_path, to_train_path,
                 from_dev_path, to_dev_path, from_vocabulary_size, to_vocabulary_size):
    """Prepare all necessary files that are required for the training.

      Args:
        data_dir: directory in which the data sets will be stored.
        from_train_path: path to the file that includes "from" training samples.
        to_train_path: path to the file that includes "to" training samples.
        from_dev_path: path to the file that includes "from" dev samples.
        to_dev_path: path to the file that includes "to" dev samples.
        from_vocabulary_size: size of the "from language" vocabulary to create and use.
        to_vocabulary_size: size of the "to language" vocabulary to create and use.

      Returns:
        A tuple of 6 elements:
          (1) path to the token-ids for "from language" training data-set,
          (2) path to the token-ids for "to language" training data-set,
          (3) path to the token-ids for "from language" development data-set,
          (4) path to the token-ids for "to language" development data-set,
          (5) path to the "from language" vocabulary file,
          (6) path to the "to language" vocabulary file.
      """
    # Create vocabularies of the appropriate sizes.
    to_vocab_path   = os.path.join(data_dir, "vocab%d.to" % to_vocabulary_size)
    from_vocab_path = os.path.join(data_dir, "vocab%d.from" % from_vocabulary_size)
    create_vocabulary(to_vocab_path, to_train_path , to_vocabulary_size)
    create_vocabulary(from_vocab_path, from_train_path , from_vocabulary_size)

    # Create token ids for the training data.
    to_train_ids_path   = to_train_path + (".ids%d" % to_vocabulary_size)
    from_train_ids_path = from_train_path + (".ids%d" % from_vocabulary_size)
    data_to_token_ids(to_train_path, to_train_ids_path, to_vocab_path)
    data_to_token_ids(from_train_path, from_train_ids_path, from_vocab_path)

    # Create token ids for the development data.
    to_dev_ids_path     = to_dev_path + (".ids%d" % to_vocabulary_size)
    from_dev_ids_path   = from_dev_path + (".ids%d" % from_vocabulary_size)
    data_to_token_ids(to_dev_path, to_dev_ids_path, to_vocab_path)
    data_to_token_ids(from_dev_path, from_dev_ids_path, from_vocab_path)

    train_ids_path  = [from_train_ids_path, to_train_ids_path]
    dev_ids_path    = [from_dev_ids_path, to_dev_ids_path]
    vocab_path      = [from_vocab_path, to_vocab_path]
    return (train_ids_path, dev_ids_path, vocab_path)
