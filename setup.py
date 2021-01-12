from distutils.util import convert_path
from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))
metadata = dict()
with open(convert_path('src/version.py')) as metadata_file:
    exec(metadata_file.read(), metadata)

setup(
    name='python-http-api',
    version=metadata['__version__'],
    zip_safe=False,

    description='Libraries to work with external XNT APIs',

    author='XNT Ltd.',
    author_email='',
    url='https://exante.eu',

    license='GPL',

    packages=find_packages('src'),
    package_dir={'': 'src'},

    install_requires=[
        'quickfix==1.15.1',
        'ujson==1.35',
        'deepdiff>=4.0.5',
        'inflection==0.3.1',
        'requests>=2.22.0',
        'backoff==1.10.0',
        'PyJWT==1.7.1'
    ],
    setup_requires=[
        'pytest-runner'
    ],
    tests_require=[
        'pytest',
        'responses',
        'requests_mock',
    ],
)
