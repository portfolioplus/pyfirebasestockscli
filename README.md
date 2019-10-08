[![Build Status](https://travis-ci.org/portfolioplus/pyfirebasestockscli.svg?branch=master)](https://travis-ci.org/portfolioplus/pyfirebasestockscli)
[![Coverage Status](https://coveralls.io/repos/github/portfolioplus/pyfirebasestockscli/badge.svg?branch=master)](https://coveralls.io/github/portfolioplus/pyfirebasestockscli?branch=master)
[![Codacy Badge](https://api.codacy.com/project/badge/Grade/7f42400f9e794d45a35376b4cbdccd9f)](https://www.codacy.com/manual/SlashGordon/pyfirebasestockscli?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=portfolioplus/pyfirebasestockscli&amp;utm_campaign=Badge_Grade)

# pyfirebasestockscli

portfolio+ command line interface for firebase operations.

## install

```bash
pip install pyfirebasestockscli
```

## quick start
Export the following environment variables:

```bash
export DATABASE_URL=https://<name>.firebaseio.com
export CRED_JSON=/path/to/firebase_sdk.json
export DATA_ROOT=/path/to/strategies
```

Create database and delete existing:

```bash
stocks -c
```

Update prices and filter:

```bash
stocks -u
```

Update prices:

```bash
stocks -p
```

Create strategies:

```bash
stocks -s
```

## issue tracker

[https://github.com/portfolioplus/pyfirebasestockscli/issuese](https://github.com/portfolioplus/pyfirebasestockscli/issues")
