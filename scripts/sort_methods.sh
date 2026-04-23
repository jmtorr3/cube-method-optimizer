 #!/usr/bin/env bash

FILE_PATH="../workspace/scratch/data/evaluation/evaluation_20260422_150516.csv"

head -n 1 $FILE_PATH && tail -n +2 $FILE_PATH | sort -t, -k7,7nr | head -n 10


