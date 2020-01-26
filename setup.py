from setuptools import setup

setup(
    name='LabBot',
    description='Helper Slack bot for the Galloway lab',
        url='https://github.com/meson800/labbot',
        author='Christopher Johnstone',
        author_email='meson800@gmail.com',
        license='MIT',
        packages=['labbot'],
        install_requires=['beautifulsoup4', 'slackclient', 'requests'],
        zip_safe=True)
