from setuptools import setup, Extension, find_packages
import sys

desc = 'Tools for analyzing SMRT sequencing data from ribosomal ' + \
       'DNA amplicons (16S, 23S, ITS)'

if ("install" in sys.argv) and sys.version_info < (2, 7, 0):
    raise SystemExit("rDnaTools requires Python 2.7")

setup(
    name = 'rDnaTools',
    version='0.1.3',
    author='Brett Bowman',
    author_email='bbowman@pacificbiosciences.com',
    url='https://github.com/bnbowman/rDnaTools',
    description=desc,
    license=open('LICENSES.txt').read(),
    packages = find_packages('src'),
    package_dir = {'':'src'},
    zip_safe = False,
    scripts=[
        'src/rDnaPipeline.py',
        'src/rDnaPipeline_Old.py',
        'src/rDnaPipeline_Redorder.py'
    ],
    install_requires=[
        'h5py >= 2.0.1',
        'numpy >= 1.6.0',
        'pbcore >= 0.8.0'
    ],
    extras_require={
        "Consensus": [
            'pbtools.pbdagcon >= 0.2.1'
        ]
    }
)