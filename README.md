## serplint

A linter for the [Serpent](https://github.com/ethereum/serpent) language.

![screenshot](https://i.imgur.com/VXb7mtK.png)

### Installation

```sh
$ pip install --upgrade serplint
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
