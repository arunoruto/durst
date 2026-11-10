[![DeepSource](https://app.deepsource.com/gh/arunoruto/durst.svg/?label=code+coverage&show_trend=true&token=3yACUgeu8xqzW87ce_3-P18h)](https://app.deepsource.com/gh/arunoruto/durst/)

<!-- Improved compatibility of back to top link: See: https://github.com/othneildrew/Best-README-Template/pull/73 -->

<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
<!--
*** I'm using markdown "reference style" links for readability.
*** Reference links are enclosed in brackets [ ] instead of parentheses ( ).
*** See the bottom of this document for the declaration of the reference variables
*** for contributors-url, forks-url, etc. This is an optional, concise syntax you may use.
*** https://www.markdownguide.org/basic-syntax/#reference-style-links
-->

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

<!-- [![LinkedIn][linkedin-shield]][linkedin-url] -->

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/arunoruto/durst">
    <picture>
      <source srcset=".github/img/durst-light.svg" media="(prefers-color-scheme: dark)">
      <img src=".github/img/durst-dark.svg" width="160" height="160">
    </picture>
    <!-- <h3>🥤</h3> -->
  </a>

  <h3 align="center">durst</h3>

  <p align="center">
    Python Registry for Organized Softdrink Transactions
    <br />
    <a href="https://github.com/arunoruto/durst"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/arunoruto/durst">View Demo</a>
    ·
    <a href="https://github.com/arunoruto/durst/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
    ·
    <a href="https://github.com/arunoruto/durst/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->

## About The Project

<!-- [![Product Name Screen Shot][product-screenshot]](https://example.com) -->

**durst** is a Python-based registry system designed to manage and track soft drink transactions in an organized manner. Whether you're managing a small office fridge or a larger beverage distribution system, durst helps you keep track of inventory, purchases, and consumption.

Key Features:

- 📊 Track soft drink inventory and transactions
- 💰 Monitor purchases and consumption patterns
- 📈 Generate reports and analytics
- 🔐 Secure user management and authentication
- 🎯 [Add more features here as they're developed]

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

<!-- This section should list any major frameworks/libraries used to bootstrap your project. Leave any add-ons/plugins for the acknowledgements section. Here are a few examples. -->

- [![Python][Python.org]][Python-url]
- [Add other frameworks/libraries here]

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->

## Getting Started

This section provides instructions on setting up durst locally. Follow these simple steps to get a local copy up and running.

### Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.8 or higher
  ```sh
  python --version
  ```
- pip (Python package installer)
  ```sh
  pip --version
  ```

### Installation

1. Clone the repo
   ```sh
   git clone https://github.com/arunoruto/durst.git
   ```
2. Navigate to the project directory
   ```sh
   cd durst
   ```
3. Create a virtual environment (optional but recommended)
   ```sh
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
4. Install required packages

   ```sh
   pip install -r requirements.txt
   ```

   <!-- Note: If requirements.txt doesn't exist yet, create it with project dependencies -->

5. Set up configuration
   ```sh
   # Copy example configuration and edit as needed
   cp config.example.yml config.yml
   ```
   <!-- Note: Update this section once configuration files are created -->

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- USAGE EXAMPLES -->

## Usage

### Hosting (Docker)

```sh
docker compose up -d --build   # serves the TUI over SSH; data + host key live in ./data
```

Then anyone can connect, no account needed:

```sh
ssh drinks.example.org         # any username works
```

- **Approved key**: you're logged in and can buy drinks for yourself. Admins also buy for others and approve sign-ups.
- **Unknown key**: read-only guest view; press `r` to register. Pick a new name or the name you already have in the sheet to take over that account. An admin approves you in the *Approvals* tab.
- **No key**: read-only guest view.

Keys: `j/k` up/down, `g/G` top/bottom, `h/l` or `←/→` switch tabs, `1-4` jump to a tab, `b` buy, `?` full help, `q` quit.

### Administration

Run the CLI inside the container (it uses `/data/durst.db` via `DURST_DB`):

```sh
alias durst='docker compose exec durst durst'
durst user add Alice alice@example.org
durst user promote Alice                             # admins are only made here
durst user key Alice "$(cat alice_id_ed25519.pub)"   # or let Alice register herself
durst drink add Mate --brand "Club-Mate"
durst stock add Kasse -i Mate:0.95:20                # bought from the pot
durst stock add Alice -i Mate:0.95:20                # Alice paid; she's credited per bottle
durst deposit Bob 20                                 # Bob put 20 € into the pot
durst repay Bob Alice 5                              # Bob paid Alice 5 € directly
```

`durst --help` lists everything. Running `durst` without a subcommand opens the TUI locally with full admin rights.

### Google Sheet sync

durst syncs both ways with the legacy *Getränkekasse* sheet while people switch over:

1. Create a Google Cloud service account, download its JSON key, and share the sheet with the account's email as an **editor**.
2. Save the key as `data/google-service-account.json`, set `DURST_SHEET_ID` in `compose.yaml`, and restart. `durst serve` then syncs every 5 minutes (`--sync-interval`); `durst sync` runs a sync right away.

The first sync imports everything. From then on, durst exchanges new drinks, orders and deposits with the sheet. The sheet's shared pot becomes the `Kasse` user. To keep track, durst writes:

- a key into a new `durst` column (F in *Preise & Bestellungen*, J in *Getränkeentnahmen*) — don't edit it
- money that only exists in durst (deposits, repayments, stock someone paid for) into column E *Einzahlungen durst* of *Kontenübersicht*, and changes *Guthaben* to `=B+E-C`
- new users and drinks into the dropdowns

A row is imported once it is unchanged for one sync interval, so half-typed rows wait. Once synced, fix mistakes in durst: edits to synced rows in the sheet are ignored, and deleted rows come back.

<!-- ROADMAP -->

## Roadmap

- [x] Initial project setup
- [x] Repository structure
- [x] Database integration
  - [ ] Update user information
  - [ ] Abstract class for different backends
- [ ] Core transaction management
  - [ ] Add transaction
  - [ ] View transaction history
  - [ ] Edit/Delete transactions
- [ ] Inventory management
  - [ ] Track stock levels
  - [ ] Low stock alerts
- [ ] Reporting features
  - [ ] Daily/Weekly/Monthly reports
  - [ ] User consumption analytics
- [ ] User interface
  - [ ] CLI interface
  - [ ] Web interface (optional)
- [ ] API development
- [ ] Documentation
- [ ] Unit tests

See the [open issues](https://github.com/arunoruto/durst/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->

## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Top contributors:

<a href="https://github.com/arunoruto/durst/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=arunoruto/durst" alt="contrib.rocks image" />
</a>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- LICENSE -->

## License

Distributed under the MIT License. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTACT -->

## Contact

Mirza Arnaut - [@your_twitter](https://twitter.com/your_twitter) - your.email@example.com

Project Link: [https://github.com/arunoruto/durst](https://github.com/arunoruto/durst)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ACKNOWLEDGMENTS -->

## Acknowledgments

Resources and libraries that have been helpful in building durst:

- [Choose an Open Source License](https://choosealicense.com)
- [GitHub Emoji Cheat Sheet](https://www.webpagefx.com/tools/emoji-cheat-sheet)
- [Malven's Flexbox Cheatsheet](https://flexbox.malven.co/)
- [Malven's Grid Cheatsheet](https://grid.malven.co/)
- [Img Shields](https://shields.io)
- [GitHub Pages](https://pages.github.com)
- [Font Awesome](https://fontawesome.com)
- [React Icons](https://react-icons.github.io/react-icons/search)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->

[contributors-shield]: https://img.shields.io/github/contributors/arunoruto/durst.svg?style=for-the-badge
[contributors-url]: https://github.com/arunoruto/durst/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/arunoruto/durst.svg?style=for-the-badge
[forks-url]: https://github.com/arunoruto/durst/network/members
[stars-shield]: https://img.shields.io/github/stars/arunoruto/durst.svg?style=for-the-badge
[stars-url]: https://github.com/arunoruto/durst/stargazers
[issues-shield]: https://img.shields.io/github/issues/arunoruto/durst.svg?style=for-the-badge
[issues-url]: https://github.com/arunoruto/durst/issues
[license-shield]: https://img.shields.io/github/license/arunoruto/durst.svg?style=for-the-badge
[license-url]: https://github.com/arunoruto/durst/blob/master/LICENSE
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/your-linkedin-username
[product-screenshot]: images/screenshot.png
[Python.org]: https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white
[Python-url]: https://www.python.org/
