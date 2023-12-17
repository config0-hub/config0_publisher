from distutils.core import setup
from setuptools import find_packages

pkgdir="config0_publisher"
version = "0.300"

setup(name='config0_publisher',
      version=version,
      description='The helper package for publishing on config0.com',
      long_description='The helper package for publishing on config0.com',
      url='http://github.com/config0-publish/config0_publisher',
      author='Gary Leong',
      author_email='gary@config0.com',
      license="Copyright Jiffy, LLC 2023",
      packages=find_packages(),
      include_package_data=True,
      install_requires=[
      ],
      classifiers=[
          "Programming Language :: Python :: 3",
          "Intended Audience :: Developers",
          "Topic :: Software Development",
          "Topic :: Utilities",
          "Environment :: Console",
          "Operating System :: OS Independent",
      ],
      zip_safe=False)
