[![Version](https://img.shields.io/npm/v/@website-scraper/puppeteer-version-wrapper.svg?style=flat)](https://www.npmjs.com/package/@website-scraper/puppeteer-version-wrapper)
[![Downloads](https://img.shields.io/npm/dm/@website-scraper/puppeteer-version-wrapper.svg?style=flat)](https://www.npmjs.com/package/@website-scraper/puppeteer-version-wrapper)
[![Test compatibility with puppeteer](https://github.com/website-scraper/puppeteer-version-wrapper/actions/workflows/test-compatibility.yaml/badge.svg?branch=main)](https://github.com/website-scraper/puppeteer-version-wrapper/actions/workflows/test-compatibility.yaml)

# @website-scraper/puppeteer-version-wrapper

A wrapper module around `puppeteer` package that ensures [website-scraper-puppeteer](https://www.npmjs.com/package/website-scraper-puppeteer) always work with the latest supported version of Puppeteer.

`website-scraper-puppeteer` is tightly coupled to a specific Puppeteer major version, which quickly becomes outdated and unsupported.

To solve this issue, `website-scraper-puppeteer` is now depends on `@website-scraper/puppeteer-version-wrapper`, which automatically manages Puppeteer updates.

This module automatically updates its Puppeteer dependency using Dependabot and continuous integration. When tests pass, a new minor version is published to NPM, keeping compatibility up-to-date without manual intervention.

## Sponsors
Maintenance of this project is made possible by all the [contributors](https://github.com/website-scraper/puppeteer-version-wrapper/graphs/contributors) and [sponsors](https://github.com/sponsors/s0ph1e).
If you'd like to sponsor this project and have your avatar or company logo appear below [click here](https://github.com/sponsors/s0ph1e). 💖

<!-- sponsors --><a href="https://github.com/aivus"><img src="https:&#x2F;&#x2F;github.com&#x2F;aivus.png" width="60px" alt="User avatar: Illia Antypenko" /></a><a href="https://github.com/swissspidy"><img src="https:&#x2F;&#x2F;github.com&#x2F;swissspidy.png" width="60px" alt="User avatar: Pascal Birchler" /></a><a href="https://github.com/itscarlosrufo"><img src="https:&#x2F;&#x2F;github.com&#x2F;itscarlosrufo.png" width="60px" alt="User avatar: Carlos Rufo" /></a><a href="https://github.com/francescamarano"><img src="https:&#x2F;&#x2F;github.com&#x2F;francescamarano.png" width="60px" alt="User avatar: Francesca Marano" /></a><a href="https://github.com/github"><img src="https:&#x2F;&#x2F;github.com&#x2F;github.png" width="60px" alt="User avatar: GitHub" /></a><a href="https://github.com/Belrestro"><img src="https:&#x2F;&#x2F;github.com&#x2F;Belrestro.png" width="60px" alt="User avatar: Andrew Vorobiov" /></a><a href="https://github.com/Effiezhu"><img src="https:&#x2F;&#x2F;github.com&#x2F;Effiezhu.png" width="60px" alt="User avatar: " /></a><a href="https://github.com/slicemedia"><img src="https:&#x2F;&#x2F;github.com&#x2F;slicemedia.png" width="60px" alt="User avatar: " /></a><!-- sponsors -->

## How It Works

- Monitors Puppeteer releases via Dependabot
- Automatically merges updates after successful tests
- Publishes new minor versions to NPM
- Ensures `website-scraper-puppeteer` always uses a compatible Puppeteer version
