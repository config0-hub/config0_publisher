export PYTHON_DIR=${PYTHON_DIR:=/usr/local/lib/python3.9/dist-packages}
export CURRENT_DIR=`pwd`
export VERSION="0.300"

export CODE_DIR="config0_publisher"

pip uninstall $CODE_DIR -y
rm -rf $PYTHON_DIR/${CODE_DIR}
pip install dist/${CODE_DIR}-${VERSION}.tar.gz
