export MAIN_DIR="config0_publisher"
export CODE_DIR="config0_publisher"
export CURRENT_DIR=`pwd`
export BUILD_ID=${BUILD_ID:-$(pwgen -s 12 1)}

echo "#$BUILD_ID" > release

# Erase previous packages
rm -rf dist $MAIN_DIR.egg-info

python setup.py sdist
