#!/bin/bash

echo "installing scipy"
sudo apt-get install -y python3-scipy

echo "installing dependencies"
pip install -r requirements.txt

while true; do
    read -p "Do you wish to create a service ?" yn
    case $yn in
        [Yy]* ) echo "[Unit]\nDescription=PlantSat service\nAfter=multi-user.target\n\r[Service]\nType=simple\nRestart=always\nExecStart=/usr/bin/python3 $(pwd)/main.py\n\r[Install]\nWantedBy=multi-user.target" > $(pwd)/plantsat.service; sudo mv $(pwd)/plantsat.service /etc/systemd/system;sudo systemctl start plantsat.service; echo "sevice is starting"; echo "cleaning up"; sudo rm $(pwd)/requirements.txt;break;;
        [Nn]* ) exit;;
        * ) echo "Please answer yes or no.";;
    esac
done
rm $(pwd)/build.sh