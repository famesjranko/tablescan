# file name: show_tables.py
#
# author: Andrew McDonald
# date: 13/08/21
#
# Description:
#   script to look through current workding directory and display
#   any found files matching file type (choice between .csv, .json)
#   and prints data from files (tables) to terminal
#
# Usage:
#   run cmd: python show_tables 'file_type'
#       set file_type to desired format and run in directory where files
#       wanted to be shown are located.
#
# Help:
#   run cmd: python show_tables --help
#


# get dependencies
import json, os, ntpath
import pandas as pd
from tabulate import tabulate
import argparse


def print_tables(file_type):
    # get current working directory
    wd = os.getcwd()

    # show files
    for file in sorted(os.listdir(wd), key=len):
        input(f'press any key to see table from: {str(file)}')
        
        if file_type == 'json' and file.endswith('.'.join([file_type])):
            with open(os.path.join(wd, file)) as handle:
                parsed = json.load(handle)
                print(json.dumps(parsed, indent=4, sort_keys=True))
                continue
        elif file_type == 'csv' and file.endswith('.'.join([file_type])):
            df = pd.read_csv(os.path.join(wd, file))
            print(tabulate(df, headers='keys', tablefmt='psql'))
            continue
    
    return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description = 'print table files to terminal')
    parser.add_argument("file_type", help="choose between csv and json to display tables from type file", type=str)
    args = parser.parse_args()
    
    types = ['csv', 'json']
    
    if args.file_type not in types:
        print(f'Sorry... file_type not available; please choose between: {types}')
    else:
        print_tables(args.file_type)