import json
import os
import re
import shutil
import logging
from typing import Callable, List, Tuple, Dict, Union
from collections import defaultdict

from .utils import create_path, load_transformer_tokenizer, load_transformer_config
from .special_tokens import BOS_TOKEN, EOS_TOKEN


class BaseParams():
    # pylint: disable=attribute-defined-outside-init
    def __init__(self):
        self.run_problem_list = []

        self.problem_type = {
        }

        # transformers params
        self.transformer_model_name = 'bert-base-chinese'
        self.transformer_tokenizer_name = 'bert-base-chinese'
        self.transformer_config_name = 'bert-base-chinese'
        self.transformer_model_loading = 'TFAutoModel'
        self.transformer_config_loading = 'AutoConfig'
        self.transformer_tokenizer_loading = 'AutoTokenizer'
        self.transformer_decoder_model_name = None
        self.transformer_decoder_config_name = None
        self.transformer_decoder_tokenizer_name = None
        # self.transformer_decoder_model_name = "hfl/chinese-xlnet-base"
        # self.transformer_decoder_config_name = "hfl/chinese-xlnet-base"
        # self.transformer_decoder_tokenizer_name = "hfl/chinese-xlnet-base"
        self.transformer_decoder_model_loading = 'TFAutoModel'
        self.transformer_decoder_config_loading = 'AutoConfig'
        self.transformer_decoder_tokenizer_loading = 'AutoTokenizer'

        # multimodal params
        self.modal_segment_id = {
            'text': 0,
            'image': 0,
            'others': 0
        }
        self.modal_type_id = {
            'text': 0,
            'image': 1,
            'others': 2
        }
        self.enable_modal_type = False
        # bert config
        self.init_checkpoint = ''

        # specify this will make key reuse values top
        # that it, weibo_ner problem will use NER's top
        self.share_top = {
        }
        for p in self.problem_type:
            if p not in self.share_top:
                self.share_top[p] = p

        self.multitask_balance_type = 'data_balanced'
        # self.multitask_balance_type = 'problem_balanced'

        # logging control
        self.log_every_n_steps = 100
        self.detail_log = True

        self.multiprocess = True
        self.num_cpus = 4
        self.per_cpu_buffer = 3000
        self.decode_vocab_file = None
        self.eval_throttle_secs = 600

        # training
        self.init_lr = 2e-5
        self.batch_size = 32
        self.train_epoch = 15
        self.freeze_step = 0
        self.prefetch = 5000
        self.dynamic_padding = True
        self.bucket_batch_sizes = [32, 32, 32, 16]
        self.bucket_boundaries = [30, 64, 128]

        # hparm
        self.dropout_keep_prob = 0.9
        self.max_seq_len = 256
        self.use_one_hot_embeddings = True
        self.label_smoothing = 0.0
        self.crf = False
        self.bert_num_hidden_layer = 12
        self.hidden_dense = False
        # threshold to calculate metrics for multi_cls
        self.multi_cls_threshold = 0.5
        self.multi_cls_positive_weight = 1.0

        # seq2seq
        self.decoder_num_hidden_layers = 3
        self.beam_size = 10
        self.init_decoder_from_encoder = False
        self.beam_search_alpha = 0.6
        self.decode_max_seq_len = 90

        # experimental multitask approach
        self.label_transfer = False
        # train mask lm and downstream task at the same time
        self.augument_mask_lm = False
        self.augument_rate = 0.5
        # NOT implemented
        self.distillation = False
        # Multi-Task Learning Using Uncertainty to Weigh Losses for Scene Geometry and Semantics
        # ref: https://arxiv.org/abs/1705.07115
        self.uncertain_weight_loss = False
        # dep since not good
        # self.mutual_prediction = False

        # add an extra attention for each task
        #   with BERT layers as encoder output, task logits as decoder inputs
        self.grid_transformer = False

        # add an extra attention for each task
        #   with other tasks' logits as encoder output, task logits asn decoder inputs
        self.task_transformer = False

        # do a mean for gradients of BERT layers instead of sum
        self.mean_gradients = False

        # random replace punctuation by some prob to
        # ease the punctuation sensitive problem
        self.punc_replace_prob = 0.0
        self.punc_list = list(',.!?！。？，、')
        self.hidden_gru = False
        self.label_transfer_gru = False
        # if None, we will use the same hidden_size as inputs
        # e.g. # of labels
        self.label_transfer_gru_hidden_size = None

        # pretrain hparm
        self.dupe_factor = 10
        self.short_seq_prob = 0.1
        self.masked_lm_prob = 0.15
        self.max_predictions_per_seq = 20
        self.mask_lm_hidden_size = 768
        self.mask_lm_hidden_act = 'gelu'
        self.mask_lm_initializer_range = 0.02

        self.train_problem = None
        self.tmp_file_dir = 'tmp'
        self.cache_dir = 'models/transformers_cache'
        # get generator function for each problem
        self.read_data_fn = {}
        self.problem_assigned = False

    def add_problem(self, problem_name: str, problem_type='cls', processing_fn: Callable = None):
        """Add problems.

        Args:
            problem_name (str): problem name. 
            problem_type (str, optional): One of the following problem types:
                ['cls', 'seq_tag', 'seq2seq_tag', 'seq2seq_text', 'multi_cls', 'pretrain']. 
                Defaults to 'cls'.
            processing_fn (Callable, optional): preprocessing function. Defaults to None.

        Raises:
            ValueError: unexpected problem_type
        """

        if problem_type not in [
                'cls', 'seq_tag', 'seq2seq_tag', 'seq2seq_text', 'multi_cls', 'pretrain']:
            raise ValueError('Provided problem type not valid, expect {0}, got {1}'.format(
                ['cls', 'seq_tag', 'seq2seq_tag',
                    'seq2seq_text', 'multi_cls', 'pretrain'],
                problem_type))

        self.problem_type[problem_name] = problem_type
        self.read_data_fn[problem_name] = processing_fn

    def add_multiple_problems(self, problem_type_dict: Dict[str, str], processing_fn_dict: Dict[str, Callable] = None):
        """add multiple problems.
        processing_fn_dict is optional, if it's not provided, processing fn will be set as None.

        Args:
            problem_type_dict (Dict[str, str]): problem type dict
            processing_fn_dict (Dict[str, Callable], optional): problem type fn. Defaults to None.
        """
        # add new problem to params if problem_type_dict and processing_fn_dict provided
        for new_problem, problem_type in problem_type_dict.items():
            print('Adding new problem {0}, problem type: {1}'.format(
                new_problem, problem_type_dict[new_problem]))
            if processing_fn_dict:
                new_problem_processing_fn = processing_fn_dict[new_problem]
            else:
                new_problem_processing_fn = None
            self.add_problem(
                problem_name=new_problem, problem_type=problem_type, processing_fn=new_problem_processing_fn)

    def assign_problem(self,
                       flag_string: str,
                       gpu=2,
                       base_dir: str = None,
                       dir_name: str = None,
                       predicting=False):
        """Assign the actual run problem to param. This function will
        do the following things:

        1. parse the flag string to form the run_problem_list
        2. create checkpoint saving path
        3. calculate total number of training data and training steps
        4. scale learning rate with the number of gpu linearly

        Arguments:
            flag_string {str} -- run problem string
            example: cws|POS|weibo_ner&weibo_cws

        Keyword Arguments:
            gpu {int} -- number of gpu use for training, this
                will affect the training steps and learning rate (default: {2})
            base_dir {str} -- base dir for ckpt, if None,
                then "models" is assigned (default: {None})
            dir_name {str} -- dir name for ckpt, if None,
                will be created automatically (default: {None})
        """
        self.assigned_details = (
            flag_string, gpu, base_dir, dir_name, predicting)
        self.problem_assigned = True
        self.predicting = predicting

        self.problem_list, self.problem_chunk = self.parse_problem_string(
            flag_string)

        # create dir and get vocab, config
        self.prepare_dir(base_dir, dir_name, self.problem_list)

        self.get_data_info(self.problem_list, self.ckpt_dir)

        self.set_data_sampling_strategy()

        if not predicting:
            self.shuffle_buffer = min([200000, self.data_num])
            for problem in self.problem_list:
                if self.problem_type[problem] == 'pretrain':
                    dup_fac = self.dupe_factor
                    break
                else:
                    dup_fac = 1
            self.train_steps = int((
                self.data_num * self.train_epoch * dup_fac) / (self.batch_size*max(1, gpu)))
            self.train_steps_per_epoch = int(
                self.train_steps / self.train_epoch)
            self.num_warmup_steps = int(0.1 * self.train_steps)

            # linear scale learing rate
            self.lr = self.init_lr * gpu

    def to_json(self):
        """Save the params as json files. Please note that processing_fn is not saved.
        """
        dump_dict = {}
        for att_name, att in vars(self).items():
            try:
                json.dumps(att)
                dump_dict[att_name] = att
            except TypeError:
                pass

        with open(self.params_path, 'w', encoding='utf8') as f:
            json.dump(dump_dict, f)

    def from_json(self, json_path: str = None):
        """Load json file as params. 

        json_path could not be None if the problem is not assigned to params

        Args:
            json_path (str, optional): Path to json file. Defaults to None.

        Raises:
            AttributeError
        """
        try:
            params_path = json_path if json_path is not None else self.params_path
        except AttributeError:
            raise AttributeError(
                'Either json_path should not be None or problem is assigned.')
        if self.problem_assigned:
            assign_details = self.assigned_details
        else:
            assign_details = None

        with open(params_path, 'r', encoding='utf8') as f:
            dump_dict = json.load(f)
        for att in dump_dict:
            setattr(self, att, dump_dict[att])
        self.bert_config = load_transformer_config(
            self.bert_config_dict, self.transformer_config_loading)
        if hasattr(self, 'bert_decoder_config_dict'):
            self.bert_decoder_config = load_transformer_config(
                self.bert_decoder_config_dict, self.transformer_decoder_config_loading
            )
        if assign_details:
            self.assign_problem(*assign_details)

    def get_data_info(self, problem_list: List[str], base: str):
        '''Get number of data, number of classes of data and eos_id of data.

        Arguments:
            problem_list {list} -- problem list
            base {str} -- path to store data_info.json
        '''

        json_path = os.path.join(base, 'data_info.json')
        if os.path.exists(json_path):
            data_info = json.load(open(json_path, 'r', encoding='utf8'))
            self.data_num_dict = data_info['data_num']
            self.num_classes = data_info['num_classes']
        elif self.predicting:
            data_info = {
                'data_num': self.data_num_dict,
                'num_classes': self.num_classes,
            }
            return json.dump(data_info, open(json_path, 'w', encoding='utf8'))
        else:
            if not hasattr(self, 'data_num_dict'):
                self.data_num_dict = {}
            if not hasattr(self, 'num_classes'):
                self.num_classes = {}

        if not self.predicting:
            # update data_num and train_steps
            self.data_num = 0
            for problem in problem_list:
                if problem not in self.data_num_dict:

                    self.data_num_dict[problem], self.num_classes[problem] = self.read_data_fn[problem](
                        self, 'train', get_data_num=True)
                    self.data_num += self.data_num_dict[problem]
                else:
                    self.data_num += self.data_num_dict[problem]

            data_info = {
                'data_num': self.data_num_dict,
                'num_classes': self.num_classes,
            }

            json.dump(data_info, open(json_path, 'w', encoding='utf8'))
        return json_path

    def parse_problem_string(self, flag_string: str) -> Tuple[List[str], List[List[str]]]:
        '''Parse problem string
        Example:
            cws|POS|weibo_ner&weibo_cws

            self.run_problem_list = [{cws:seq_tag}, {POS:seq_tag}, {weibo_ner:seq_tag, weibo_cws:seq_tag}]
            problem_list = [cws, POS, weibo_ner, weibo_cws]
            problem_chunk = [[cws], [POS], [weibo_ner, weibo_cws]]

        Arguments:
            flag_string {str} -- problem string

        Returns:
            list -- problem list
        '''

        self.problem_str = flag_string
        # Parse problem string
        self.run_problem_list = []
        problem_chunk = []
        for flag_chunk in flag_string.split('|'):

            if '&' not in flag_chunk:
                problem_type = {}
                problem_type[flag_chunk] = self.problem_type[flag_chunk]
                self.run_problem_list.append(problem_type)
                problem_chunk.append([flag_chunk])
            else:
                problem_type = {}
                problem_chunk.append([])
                for problem in flag_chunk.split('&'):
                    problem_type[problem] = self.problem_type[problem]
                    problem_chunk[-1].append(problem)
                self.run_problem_list.append(problem_type)
        # if (self.label_transfer or self.mutual_prediction) and self.train_problem is None:
        if self.train_problem is None:
            self.train_problem = [p for p in self.run_problem_list]

        problem_list = sorted(re.split(r'[&|]', flag_string))
        return problem_list, problem_chunk

    def prepare_dir(self, base_dir: str, dir_name: str, problem_list: List[str]):
        """prepare model checkpoint dir. this function will copy or save transformers' configs
        and tokenizers to params.ckpt_dir

        Args:
            base_dir (str): base_dir of params.ckpt_dir. same as os.path.dirname(params.ckpt_dir). bad naming
            dir_name (str): dir_name, same as os.path.basename(params.ckpt_dir). bad naming
            problem_list (List[str]): [description]
        """
        base = base_dir if base_dir is not None else 'models'

        dir_name = dir_name if dir_name is not None else '_'.join(
            problem_list)+'_ckpt'
        self.ckpt_dir = os.path.join(base, dir_name)

        # we need to make sure all configs, tokenizers are in ckpt_dir
        # configs
        from_config_path = os.path.join(self.init_checkpoint,
                                        'bert_config')
        from_decoder_config_path = os.path.join(self.init_checkpoint,
                                                'bert_decoder_config')
        to_config_path = os.path.join(self.ckpt_dir, 'bert_config')
        to_decoder_config_path = os.path.join(
            self.ckpt_dir, 'bert_decoder_config')

        # tokenizers
        from_tokenizer_path = os.path.join(self.init_checkpoint, 'tokenizer')
        to_tokenizer_path = os.path.join(self.ckpt_dir, 'tokenizer')

        from_decoder_tokenizer_path = os.path.join(
            self.init_checkpoint, 'decoder_tokenizer')
        to_decoder_tokenizer_path = os.path.join(
            self.ckpt_dir, 'decoder_tokenizer')

        self.params_path = os.path.join(self.ckpt_dir, 'params.json')

        if not self.predicting:
            create_path(self.ckpt_dir)

            # two ways to init model
            # 1. init from TF checkpoint dir created by bert-multitask-learning.
            # 2. init from huggingface checkpoint.

            # bert config exists, init from existing config
            if os.path.exists(from_config_path):
                # copy config
                shutil.copy2(from_config_path, to_config_path)
                self.bert_config = load_transformer_config(
                    to_config_path, self.transformer_config_loading)

                # copy tokenizer
                shutil.copy2(from_tokenizer_path, to_tokenizer_path)

                # copy decoder config
                if os.path.exists(from_decoder_config_path):
                    shutil.copy2(from_decoder_config_path,
                                 to_decoder_config_path)
                    self.bert_decoder_config = load_transformer_config(
                        from_decoder_config_path, self.transformer_decoder_config_loading
                    )
                    self.bert_decoder_config_dict = self.bert_decoder_config.to_dict()
                # copy decoder tokenizer
                if os.path.exists(from_decoder_tokenizer_path):
                    shutil.copy2(from_decoder_tokenizer_path,
                                 to_decoder_tokenizer_path)

                self.init_weight_from_huggingface = False
            else:
                # load config from huggingface
                logging.warning(
                    '%s not exists. will load model from huggingface checkpoint.', from_config_path)
                # get or download config
                self.init_weight_from_huggingface = True
                self.bert_config = load_transformer_config(
                    self.transformer_config_name, self.transformer_config_loading)
                self.bert_config.save_pretrained(to_config_path)

                # save tokenizer
                tokenizer = load_transformer_tokenizer(
                    self.transformer_tokenizer_name, self.transformer_tokenizer_loading)
                tokenizer.save_pretrained(to_tokenizer_path)
                # save_pretrained method of tokenizer saves the config as tokenizer_config.json, which will cause
                # OSError if use tokenizer.from_pretrained directly. we need to manually rename the json file
                try:
                    os.rename(os.path.join(to_tokenizer_path, 'tokenizer_config.json'), os.path.join(
                        to_tokenizer_path, 'config.json'))
                except:
                    pass

                # if decoder is specified
                if self.transformer_decoder_model_name:
                    self.bert_decoder_config = load_transformer_config(
                        self.transformer_decoder_config_name, self.transformer_decoder_config_loading
                    )
                    self.bert_decoder_config_dict = self.bert_decoder_config.to_dict()
                    self.bert_decoder_config.save_pretrained(
                        to_decoder_config_path)
                    decoder_tokenizer = load_transformer_tokenizer(
                        self.transformer_decoder_tokenizer_name, self.transformer_decoder_tokenizer_loading)
                    decoder_tokenizer.save_pretrained(
                        to_decoder_tokenizer_path)
                    try:
                        os.rename(os.path.join(to_decoder_tokenizer_path, 'tokenizer_config.json'), os.path.join(
                            to_decoder_tokenizer_path, 'config.json'))
                    except:
                        pass
        else:
            self.bert_config = load_transformer_config(to_config_path)
            if os.path.exists(to_decoder_config_path):
                self.bert_decoder_config = load_transformer_config(
                    to_decoder_config_path)
            self.init_weight_from_huggingface = False

        self.transformer_config_name = to_config_path
        # set value if and only if decoder is assigned
        self.transformer_decoder_config_name = to_decoder_config_path if self.transformer_decoder_config_name is not None else None
        self.transformer_tokenizer_name = to_tokenizer_path
        # set value if and only if decoder is assigned
        self.transformer_decoder_tokenizer_name = to_decoder_tokenizer_path if self.transformer_decoder_tokenizer_name is not None else None

        self.bert_config_dict = self.bert_config.to_dict()

        tokenizer = load_transformer_tokenizer(
            self.transformer_tokenizer_name, self.transformer_tokenizer_loading)
        self.vocab_size = tokenizer.vocab_size
        if self.transformer_decoder_tokenizer_name:
            decoder_tokenizer = load_transformer_tokenizer(
                self.transformer_decoder_tokenizer_name,
                self.transformer_decoder_tokenizer_loading
            )

            # if set bos and eos
            if decoder_tokenizer.bos_token is None:
                decoder_tokenizer.add_special_tokens({'bos_token': BOS_TOKEN})

            if decoder_tokenizer.eos_token is None:
                decoder_tokenizer.add_special_tokens({'eos_token': EOS_TOKEN})

            # overwrite tokenizer
            decoder_tokenizer.save_pretrained(to_decoder_tokenizer_path)

            self.decoder_vocab_size = decoder_tokenizer.vocab_size
            self.bos_id = decoder_tokenizer.bos_token_id
            self.eos_id = decoder_tokenizer.eos_token_id

    def get_problem_type(self, problem: str) -> str:
        return self.problem_type[problem]

    def update_train_steps(self, train_steps_per_epoch: int, epoch: int = None) -> None:
        """If the batch_size is dynamic, we have to loop through the tf.data.Dataset
        to get the accurate number of training steps. In this case, we need a function to
        update the train_steps which will be used to calculate learning rate schedule.

        WARNING: updating should be called before the model is compiled! 

        Args:
            train_steps (int): new number of train_steps
        """
        if epoch:
            train_steps = train_steps_per_epoch * epoch
        else:
            train_steps = train_steps_per_epoch * self.train_epoch

        logging.info('Updating train_steps from {0} to {1}'.format(
            self.train_steps, train_steps))

        self.train_steps = train_steps
        self.train_steps_per_epoch = train_steps_per_epoch
        self.num_warmup_steps = int(self.train_steps * 0.1)

    def get_problem_chunk(self, as_str=True) -> Union[List[str], List[List[str]]]:

        if as_str:
            res_list = []
            for problem_list in self.problem_chunk:
                res_list.append('_'.join(sorted(problem_list)))
            return res_list
        else:
            return self.problem_chunk

    def set_data_sampling_strategy(self,
                                   sampling_strategy='data_balanced',
                                   sampling_strategy_fn: Callable = None) -> Dict[str, float]:
        """Set data sampling strategy for multi-task learning.

        'data_balanced' and 'problem_balanced' is implemented by default.
        data_balanced: sampling weight equals to number of rows of that problem chunk.
        problem_balanced: sampling weight equals to 1 for every problem chunk.

        Args:
            sampling_strategy (str, optional): sampling strategy. Defaults to 'data_balanced'.
            sampling_strategy_fn (Callable, optional): function to create weight dict. Defaults to None.

        Raises:
            NotImplementedError: sampling_strategy_fn is not implemented yet
            ValueError: invalid sampling_strategy provided

        Returns:
            Dict[str, float]: sampling weight for each problem_chunk
        """
        if sampling_strategy_fn:
            logging.info(
                'sampling_strategy_fn is provided, sampling_strategy arg will be ignored.')
            raise NotImplementedError

        problem_chunk_data_num = defaultdict(float)
        if sampling_strategy == 'data_balanced':
            problem_chunk = self.get_problem_chunk(as_str=False)
            for problem_list in problem_chunk:
                str_per_chunk = '_'.join(sorted(problem_list))
                for problem in problem_list:
                    problem_chunk_data_num[str_per_chunk] += self.data_num_dict[problem]
        elif sampling_strategy == 'problem_balanced':
            problem_chunk = self.get_problem_chunk(as_str=True)
            for str_per_chunk in problem_chunk:
                problem_chunk_data_num[str_per_chunk] = 1
        else:
            raise ValueError(
                'sampling strategy {} is not implemented by default. '
                'please provide sampling_strategy_fn.'.format(sampling_strategy))

        # devided by sum to get sampling prob
        sum_across_problems = sum(
            [v for _, v in problem_chunk_data_num.items()])
        self.problem_sampling_weight_dict = {
            k: v / sum_across_problems for k, v in problem_chunk_data_num.items()}
        return self.problem_sampling_weight_dict


class CRFParams(BaseParams):
    def __init__(self):
        super(CRFParams, self).__init__()
        self.crf = True


class StaticBatchParams(BaseParams):
    def __init__(self):
        super(StaticBatchParams, self).__init__()
        self.dynamic_padding = False


class DynamicBatchSizeParams(BaseParams):
    def __init__(self):
        super(DynamicBatchSizeParams, self).__init__()
        self.bucket_batch_sizes = [128, 64, 32, 16]
