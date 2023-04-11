from setuptools import setup

setup(
    name='LabBot',
    description='Helper Slack bot for the Galloway lab',
        url='https://github.com/GallowayLabMIT/labbot',
        author='Christopher Johnstone',
        author_email='meson800@gmail.com',
        license='MIT',
        packages=['labbot'],
        install_requires=['beautifulsoup4', 'slackclient',
                          'requests', 'fastapi', 'uvicorn',
                          'python-multipart', 'pytz',
                          'slack_bolt', 'uvloop', 'paho-mqtt',
                          'rsa', 'python-dateutil', 'durations',
                          'google-api-python-client', 'google-auth-httplib2', 'google-auth-oauthlib'],
        zip_safe=True)
