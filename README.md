# python-http-api

Python library for XNT Ltd. HTTP API service Provides object-oriented access to actual endpoints (https://api-live.exante.eu/api-docs/)
All methods are strictly typed, python3.7+.

# Building and installation

Package available from github assets and pypi repository

~~python3 -m pip install python-http-api~~

# Basic usage

Main class [HTTPApi](src/xnt/http_api.py#L132) provides all neccessary methods to access API, each method has docstring with basic explanation of its usage.
Class initialization requires specification one of authentification methods: either basic auth or building JWT token.

    HTTPApi(auth=AuthMethods.JWT,
            appid='appid',
            clientid='clientid',
            sharedkey='sharedkey',
            ttl=86400
    )
or

    HTTPApi(auth=AuthMethods.BASIC,
            appid='appid',
            acckey='acckey'
    )

Global API version can be specificated upon instance creation (parameter version=), however not all API endpoints are available for all methods, in that case NotImplemented exception will be raised.

Most basic example of library usage in building stand-alone trading applications can be checked in [example](tests/http_robot.py)