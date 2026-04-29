from setuptools import setup, find_packages

setup(
    name="ai_module",
    version="1.0.0",
    description="Классификатор тикетов поддержки на базе Mistral AI",
    packages=find_packages(),
    install_requires=[
        "requests",
        "python-dotenv",
    ],
    python_requires=">=3.8",
)