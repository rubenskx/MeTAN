# Utility module to load dataset
import os
import json
import pickle

import sys
from typing import Generator, Dict, Text, List, Union
from datetime import datetime

# to fix a weird crash due to "ValueError: failed to parse CPython sys.version '3.6.6 |Anaconda, Inc.| (default, Jun 28 2018, 11:27:44) [MSC v.1900 64 bit (AMD64)]'"
# possible due to a bug on anaconda
# see https://stackoverflow.com/questions/34145861/valueerror-failed-to-parse-cpython-sys-version-after-using-conda-command
try:
    import sys  # Just in case
    start = sys.version.index('|')  # Do we have a modified sys.version?
    end = sys.version.index('|', start + 1)
    version_bak = sys.version  # Backup modified sys.version
    # Make it legible for platform module
    sys.version = sys.version.replace(sys.version[start:end+1], '')
    import platform
    platform.python_implementation()  # Ignore result, we just need cache populated
    # Duplicate cache
    platform._sys_version_cache[version_bak] = platform._sys_version_cache[sys.version]
    sys.version = version_bak  # Restore modified version string
except ValueError:  # Catch .index() method not finding a pipe
    pass

import pandas as pd
import csv
from pprint import pprint as pp
from datetime import datetime
from datetime import timedelta


import logging
from overrides import overrides
from allennlp.common.file_utils import cached_path
from allennlp.data.dataset_readers.dataset_reader import DatasetReader
from allennlp.data.fields import LabelField, TextField, Field, ListField, MetadataField
from allennlp.data.instance import Instance
from allennlp.data.token_indexers import TokenIndexer, SingleIdTokenIndexer
from allennlp.data.tokenizers import Tokenizer, SpacyTokenizer, PretrainedTransformerTokenizer
from allennlp.data.tokenizers.sentence_splitter import SpacySentenceSplitter

logger = logging.getLogger(__name__)


def load_abs_path(data_path: str) -> str:
    """
    read actual data path from either symlink or a absolute path

    :param data_path: either a directory path or a file path
    :return:
    """
    if not os.path.exists(data_path) or os.path.islink(data_path):
        return os.readlink(data_path)

    else:
        return os.path.abspath(data_path)
    return data_path


posts_dataset_dir_dict = {}
metaphors_dataset_dir_dict = {}


def load_user_posts(user_id: Text) -> Generator[Dict, None, None]:
    global posts_dataset_dir_dict, metaphors_dataset_dir_dict, post_data_dir

    # Load the posts dataset directory if not loaded
    if len(posts_dataset_dir_dict) == 0:
        posts_dataset_dir_dict = load_posts_dataset_dir(post_data_dir)

    # Load the metaphors dataset directory if not loaded
    if len(metaphors_dataset_dir_dict) == 0:
        metaphors_dataset_dir_dict = load_posts_dataset_dir(post_data_dir)

    # Get the directory for posts dataset
    posts_dataset_dir = posts_dataset_dir_dict.get(user_id)

    # If the user_id is not found in the posts dataset, return an empty generator
    if not posts_dataset_dir:
        return

    # Load the user objects from the posts dataset
    user_objs = load_post_json(os.path.join(
        posts_dataset_dir, '{}.json'.format(user_id)))

    # Check if metaphors data is available for the user
    # If no metaphors data, yield the posts as they are
    for obj in user_objs:
        post_obj = {}
        if bool(datetime.strptime(obj[0], '%Y-%m-%d %H:%M:%S')):
            post_obj['timestamp'] = obj[0]
        else:
            post_obj['timestamp'] = datetime.utcfromtimestamp(
                obj[0]).strftime('%Y-%m-%d %H:%M:%S')
        post_obj['text'] = obj[1]
        yield post_obj
    # else:
    #     # If metaphors data is available, load it
    #     metaphors_objs = load_post_json(os.path.join(
    #         metaphors_dataset_dir, '{}_cm.json'.format(user_id)))

    #     # Create a dictionary for easier lookup based on timestamp
    #     metaphors_dict = {obj[0]: obj[1] for obj in metaphors_objs}

    #     # Iterate through user_objs and append metaphors if available
    #     for obj in user_objs:
    #         post_obj = {}
    #         timestamp = obj[0]
    #         if bool(datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')):
    #             post_obj['timestamp'] = timestamp
    #         else:
    #             post_obj['timestamp'] = datetime.utcfromtimestamp(
    #                 timestamp).strftime('%Y-%m-%d %H:%M:%S')
    #         post_obj['text'] = obj[1]

    #         # Check if metaphor data is available for the timestamp
    #         if timestamp in metaphors_dict:
    #             post_obj['text'] += ". " + metaphors_dict[timestamp]
    #             # print(post_obj['text'])

    #         yield post_obj


def load_user_metaphors(user_id: Text) -> Generator[Dict, None, None]:

    global metaphors_dataset_dir_dict, post_data_dir
    if len(metaphors_dataset_dir_dict) == 0:
        metaphors_dataset_dir_dict = load_posts_dataset_dir(post_data_dir)

    user_id_str = "{}".format(user_id)
    if user_id_str in metaphors_dataset_dir_dict:
        posts_dataset_dir = metaphors_dataset_dir_dict[user_id_str]
    # Rest
    else:
        # print(f"Key '{user_id_str}' not found in metaphors_dataset_dir_dict.")
        return {}

    if os.path.exists(os.path.join(posts_dataset_dir, '{}_cm.json'.format(user_id))):
        # print("exists ")
        user_objs = load_post_json(os.path.join(
            posts_dataset_dir, '{}_cm.json'.format(user_id)))

    else:
        user_objs = []

    # if len(user_objs)==0:
    #     post_obj = {}
    #     yield post_obj
    #
    user_objs = []
    for obj in user_objs:
        post_obj = {}
        if bool(datetime.strptime(obj[0], '%Y-%m-%d %H:%M:%S')):
            post_obj['timestamp'] = obj[0]
        else:
            post_obj['timestamp'] = datetime.utcfromtimestamp(
                obj[0]).strftime('%Y-%m-%d %H:%M:%S')
        post_obj['text'] = obj[1]

        yield post_obj


def load_posts_dataset_dir(post_data_dir):
    """
    load tweet context dataset directory into a dictionary that can be mapped and
        loaded for feature extraction by source tweet id

    This method assumes that the all the context tweets (i.e., replies) are organised under a directory
        named as source tweet id.
    Thus, by the source tweet id, we can load all the replies (from its root directory or subdirectories)
    :return:dict {tweet id: context tweet dataset directory path}

    """
    print("load post data from dir: ", post_data_dir)
    post_dataset_dir = post_data_dir
    post_dataset_abs_path = load_abs_path(post_dataset_dir)
    print("post_dataset_abs_path: ", post_dataset_abs_path)
    all_subdirectories = [x[0] for x in os.walk(post_dataset_abs_path)]
    print("done.")
    return {os.path.basename(subdirectory): subdirectory for subdirectory in all_subdirectories if os.path.basename(subdirectory).isdigit()}
    # return {os.path.basename(subdirectory): subdirectory for subdirectory in all_subdirectories}


def load_post_json(post_json_path):
    try:
        with open(post_json_path, encoding='UTF-8', mode='r') as f:
            data = json.load(f)

    except UnicodeDecodeError as err:
        print("failed to process json file : %s. Error: %s" %
              (post_json_path, err.reason))
        raise err

    return data


if __name__ == '__main__':
    # test_load_source_tweet_context()
    # x = load_tweets_context_dataset_dir(social_context_data_dir)
    # pp(x)
    # x = load_user_posts('9999423')
    # for k in x:
    #     print(k)
    user_ids = load_posts_dataset_dir(post_data_dir)
    # pp(user_ids)
