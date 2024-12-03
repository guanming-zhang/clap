import os
import copy
import configparser
from itertools import product
from copy import deepcopy
import subprocess
import time
import shutil

class JobManager:
    def __init__(self,default_config_path:str):
        config = configparser.ConfigParser()
        config.read(default_config_path)
        self.base_config = config 
        self.batch_dict = {"NUM_NODES":"1",
                           "GPUS_PER_NODE":"1",
                           "CPUS_PER_TASK":"1",
                           "NTASKS_PER_NODE":"1",
                           "GRES":"gpu",
                           "CONDA_ENV":"dl_env",
                           "TIME":"100:00:00",
                           "MEM_PER_NODE":"6GB",
                           "PYTHON_EXE":"main.py",
                           "ARG1":"[input_dir_path]",
                           "ARG2":"./default_config_cifar10.ini"}
        self.default_comp_res = True
    def print_config(self,config:configparser.ConfigParser):
        for section in config.sections():
            print(f"[{section}]")
            for key, value in config[section].items():
                print(f"{key} = {value}")
            print()
    def set_computation_resource(self,num_nodes:int,gpus_per_node:int,cpus_per_gpu:int,gres:str = "gpu"):
        # update the base config
        self.base_config.set("INFO","num_nodes",str(num_nodes))
        self.base_config.set("INFO","gpus_per_node",str(gpus_per_node))
        self.base_config.set("INFO","cpus_per_gpu",str(cpus_per_gpu))
        # update the batch options
        self.batch_dict["NUM_NODES"] = str(num_nodes)
        self.batch_dict["GPUS_PER_NODE"] = str(gpus_per_node)
        self.batch_dict["CPUS_PER_TASK"] = str(cpus_per_gpu)
        # set the ntasks_per_node = gpus_per_node
        # see https://lightning.ai/docs/pytorch/stable/clouds/cluster_advanced.html
        self.batch_dict["NTASKS_PER_NODE"] = str(gpus_per_node)
        self.batch_dict["GRES"] = gres
        if gpus_per_node*num_nodes == 1:
            self.base_config.set("INFO","strategy","auto")
        self.default_comp_res = False
    
    def generate_config_combinations(self,config_options:dict)->configparser.ConfigParser:
        # Separate sections and values for each option
        sections = config_options.keys()
        options = {section: [dict(zip(config_options[section], values))
                         for values in product(*config_options[section].values())]
               for section in sections}

        # Generate Cartesian product of options across all sections
        all_combinations = product(*options.values())
        configs = []

        # Create a ConfigParser object for each combination
        for combination in all_combinations:
            config = configparser.ConfigParser()
            for section, option_dict in zip(sections, combination):
                config[section] = {key: str(value) for key, value in option_dict.items()}
            configs.append(deepcopy(config))
        return configs

    def create_directory_from_config(self,base_dir:str, config:configparser.ConfigParser,
                                     suffix:str = "",prefix:str = "")->str:
        # Generate a unique subdirectory name based on the hyperparameters
        folder_name_parts = []
        for section, options in config.items():
            if section == "DEFAULT":
                continue
            folder_name_parts.append(f"#{section}#")
            for key, value in options.items():
                folder_name_parts.append(f"{key}-{value}")
        
        # Join all parts to form the folder name
        folder_name = prefix + "-".join(folder_name_parts) + suffix

        # Create the directory using Python
        dir_path = os.path.join(base_dir,folder_name)
        # Create the directory if it doesn't exist
        os.makedirs(dir_path, exist_ok=True)
        print(dir_path)
        return dir_path
    def update_configparser(self,base_config:configparser.ConfigParser, update_config:configparser.ConfigParser):
        # Iterate over all sections in the update_config
        for section in update_config.sections():
            if not base_config.has_section(section):
                raise ValueError(f"Section '{section}' not found in base_config.")
            # Iterate over all options in the section and update base_config
            for key, value in update_config.items(section):
                base_config.set(section, key, value) 
                if not base_config.has_option(section, key):
                    raise ValueError(f"Key '{key}' not found in section '{section}' of base_config.")
    
    def write_config(self,file_path,config):
        with open(file_path, 'w') as configfile:
            config.write(configfile)
    
    def create_sbatch_file(self,batch_dict):
        with open('./submit_batch.ini', 'r') as file:
            fstring = file.read()
        for key in batch_dict:
            fstring = fstring.replace(key, batch_dict[key])
        with open('./submit_batch.sbatch', 'w') as file:
            file.write(fstring)
    
    def submit_sbatch(self,nsleep = 0.05):
        subprocess.run(["sbatch", "submit_batch.sbatch"])
        time.sleep(nsleep)
        subprocess.run(["rm", "submit_batch.sbatch"])
    
    def submit(self,base_dir:str,config_dict:dict,batch_dict:dict,n_repeat:int=1):
        if self.default_comp_res:
            print("The default computional resorcue setup is applied, use set_computation_resource() to reset if needed!")
        configs = self.generate_config_combinations(config_dict)
        print("there are {} configs in total".format(len(configs)))
        os.makedirs(base_dir, exist_ok=True)
        count = 0
        for i in range(n_repeat):
            suffix = "-run-" + f"{i:02}"
            for config in configs:
                dir_path = self.create_directory_from_config(base_dir,config,suffix,prefix="dir"+str(count))
                base_config = copy.deepcopy(self.base_config)
                self.update_configparser(base_config,config)
                self.write_config(os.path.join(dir_path,"config.ini"),base_config)
                base_batch_dict = copy.deepcopy(self.batch_dict)
                base_batch_dict["ARG1"] = dir_path
                base_batch_dict.update(batch_dict)
                self.create_sbatch_file(base_batch_dict)
                self.submit_sbatch()
                count += 1
        def continue_prev_submit(self,base_dir:str,batch_dict:dict):
            folder_list = os.listdir(base_dir)
            for folder in folder_list:
                folder_path = os.path.join(base_dir,folder)
                if not "run" in folder:
                    continue
                config = configparser.ConfigParser()
                config.read(os.path.join(folder_path,"config.ini"))
                num_nodes = config["INFO"].getint("num_nodes")
                gpus_per_node = config["INFO"].getint("gpus_per_node")
                cpus_per_gpu = config["INFO"].getint("cpus_per_node")
                self.set_computation_resource(num_nodes,gpus_per_node,cpus_per_gpu,gres="gpu")
                base_batch_dict = copy.deepcopy(self.batch_dict)
                base_batch_dict.update(batch_dict)
                base_batch_dict["ARG1"] = folder_path
                if os.path.isfile(os.path.join(folder_path,"lc","results.json")):
                    continue
                self.create_sbatch_file(base_batch_dict)
                self.submit_sbatch()       
        
        
        
if __name__ == "__main__":
    # for resnet+batch size=256+cifat10, need around 3GB mem per GPU, 3GB*gpus_per_node per node
    # around 5 minutes per epoch
    # if batch size is too small or num_cpus is too low then GPU utility will be low
    jm = JobManager("./default_config_cifar10.ini")
    options = {"SSL":{"lr":[0.1],"batch_size":[128],"lw0":[0.1,10.0],"lw2":[0.1]},
               "LC":{"lr":[0.2],}}
    # cpus_per_taks is equivalent to cpus_per_gpu in our setting
    jm.set_computation_resource(num_nodes=1,gpus_per_node=2,cpus_per_gpu=4,gres="gpu")
    jm.submit("./simulations/grid_search_test2",options,{"TIME":"06:30:00","MEM_PER_NODE":"6GB"})
    
