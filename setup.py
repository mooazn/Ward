#!/usr/bin/env python3
"""
Ward - A control plane for long-running AI agents
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8")

setup(
    name="ward",
    version="2.5.0",
    description="A control plane for long-running AI agents, enforcing explicit authority, leases, and auditability",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Ward Contributors",
    url="https://github.com/mooazn/Ward",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*", "examples"]),
    python_requires=">=3.7",
    install_requires=[
        # No runtime dependencies - intentionally minimal
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Monitoring",
    ],
    keywords="agent control authority lease monitoring audit revocation",
    project_urls={
        "Bug Reports": "https://github.com/mooazn/Ward/issues",
        "Source": "https://github.com/mooazn/Ward",
    },
)
