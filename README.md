## serplint

A linter for the [Serpent](https://github.com/ethereum/serpent) language.

![screenshot](https://i.imgur.com/VXb7mtK.png)

### Installation

Until a new release of Serpent is uploaded to PyPi it's necessary to install
like so:

```sh
$ pip install serplint
$ pip install git+https://github.com/ethereum/serpent.git@3ec98d01813167cc8725a951bd384c629158af2b#egg=ethereum-serpent
```

### Usage

```sh
$ serplint filename.se
```

### Current tests

- undefined variables

### Planned tests

- array index out of bounds
- function parameter not used in function
- function parameter shadowing
- magic numbers
- unused assignment

### Integrations

- Sublime Text 3 (pull request pending)
- neovim + neovmake (pull request pending)

TODO:

- vscode
