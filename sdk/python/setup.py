from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="feedo-sdk",
    version="0.1.15",
    description="The official Developer SDK for Feedo Protocol",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="Apache-2.0",
    author="Feedo Protocol",
    packages=find_packages(),
    install_requires=[
        'httpx>=0.27.0',
        'pydantic>=2.0.0',
        'eth-account>=0.11.0',
        'cryptography>=41.0.0',
        'eciespy>=0.4.0',
    ],
    python_requires=">=3.8",
)
