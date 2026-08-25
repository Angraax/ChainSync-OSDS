#!/bin/bash
# xv6-dev.sh — launch xv6 dev tmux session

tmux new-session -d -s xv6 -n main
tmux split-window -h -t xv6:main
tmux split-window -v -t xv6:main.1

tmux send-keys -t xv6:main.0 'nvim' C-m
tmux send-keys -t xv6:main.1 'echo "run: make qemu"' C-m
tmux send-keys -t xv6:main.2 'echo "free shell — git/grep/build"' C-m

tmux select-pane -t xv6:main.0
tmux attach-session -t xv6
