from setuptools import setup, find_packages

setup(
    name="feedo-py",
    version="1.0.0",
    description="Feedo Web3 Social Network SDK",
    packages=find_packages(),
    install_requires=[
        "ecdsa>=0.18.0",
        "requests>=2.28.0"
    ],
)
