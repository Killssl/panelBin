#!/bin/bash

rsync -avz -e "ssh" --exclude ".git" --exclude ".idea" --exclude "__pycache__" --exclude "data" . ggoduu@187.77.111.121:~/repo/panelbin