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
- reassigned arguments
- unused arguments
- unused assignment

### Planned tests

- array index out of bounds
- data and event shadowing
- magic numbers

### Integrations

- Sublime Text 3 [syntax](https://packagecontrol.io/packages/Serpent%20Syntax) and [linter](https://packagecontrol.io/packages/SublimeLinter-contrib-serplint)
- [neovim + neovmake](https://github.com/neomake/neomake/blob/663e9a73ef7f1c666feffa7f70851fb559212db7/autoload/neomake/makers/ft/serpent.vim)

### TODO

- Visual Studio Code
