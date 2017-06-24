#!/usr/bin/env python

from __future__ import print_function

import re
import sys

from collections import defaultdict, Iterable

import click
import serpent


def iterable(o):
    return isinstance(o, Iterable) and not isinstance(o, basestring)


def flatten(l):
    for el in l:
        if iterable(el):
            for sub in flatten(el):
                yield sub
        else:
            yield el


GLOBALS = [
    'block.coinbase',
    'block.difficulty',
    'block.gaslimit',
    'block.number',
    'block.prevhash',
    'block.timestamp',
    'msg.gas',
    'msg.sender',
    'msg.value',
    'self',
    'self.balance',
    'self.storage',
    'tx.gasprice',
    'x.balance',
]

BUILTINS = [
    'calldatacopy',
    'calldataload',
    'data',
    'div',
    'event',
    'log',
    'send',  # TODO verify
    'string',
    '~invalid',
]


# TODO shadowing/redefinition
#
# def init(): - executed upon contract creation, accepts no parameters
# def shared(): - executed before running init and user functions
# def any(): - executed before any user functions

# ensure things like self.controller are initialized?


class Token(object):

    def __init__(self, name, metadata):
        self.name = name
        self.metadata = metadata

    def __eq__(self, y):
        return self.name == y.name and self.metadata.ln == y.metadata.ln


class Linter(object):

    @staticmethod
    def is_reference(value):
        return (re.match('^[a-z]', value, re.IGNORECASE) and
                value not in GLOBALS and
                value not in BUILTINS)

    @staticmethod
    def is_opcode(value):
        return (re.match('^[^0-9]', value) and
                value not in GLOBALS and
                value not in BUILTINS)

    def check(self, token, method_name):
        if (self.is_reference(token.name) and
                not self.in_scope(token.name, method_name)):
            print(
                '{}:{} undefined variable "{}"'
                .format(token.metadata.ln + 1, token.metadata.ch, token.name),
                file=sys.stderr)

    def simple_traversal(self, nodes, method_name):
        if not nodes:
            return

        for token in self.gather_tokens(nodes):
            self.check(token, method_name)

    def conditional_traversal(self, node, method_name):
        """
        For if and while statements.
        """
        condition = node.args[0]

        self.simple_traversal(condition, method_name)

        return node.args[1:]

    def deep_traversal(self, node, method_name):
        return node.args

    def assignment(self, node, method_name):
        token = node.args[0].val

        if self.is_reference(token):
            self.scope[method_name][token] = 'assignment'

        for token in self.gather_tokens(node.args[1:]):
            self.check(token, method_name)

    def return_type(self, node, method_name):
        return_value = node.args[0]
        # return_type = node.args[1]

        self.simple_traversal(return_value, method_name)

    def resolve_access(self, node):
        if node.args[0].val == 'access' and len(node.args[0].args) >= 2:
            return self.resolve_access(node.args[0])

        if node.args[0].val == '.':
            return '.'.join(a.val for a in node.args[0].args)

        return node.args[0].val

    def resolve_argument(self, node):
        if isinstance(node, serpent.Token) or not node.args:
            return node.val

        if node.args[0].val == ':':
            return node.args[0].args[0].val

        return node.args[0].val

    def define_data(self, node, *args):
        # struct
        if node.args[0].val == 'fun':
            name = 'self.{}'.format(self.resolve_access(node.args[0].args[0]))

            self.data.append(name)

            for field in node.args[0].args[1:]:
                self.data.append('{}.{}'.format(name, field.val))

            # self.structs[name] = node.args[0].args[1:]
        else:
            self.data.append('self.{}'.format(self.resolve_access(node)))

    def define_event(self, node, method_name):
        self.events.append(node.args[0].val)

    # def define_extern(self, node, method_name):
    #     self.methods.append(node.args[0].val)

    def define_macro(self, node, method_name):
        name = node.args[0].val
        body = node.args[1]

        self.macros.append(name)

        return [body]

    def define_method(self, node, method_name):
        name = node.args[0].val
        arguments = node.args[0].args

        self.methods.append('self.{}'.format(name))

        for token in [self.resolve_argument(arg) for arg in arguments]:
            self.scope[name][token] = 'argument'

        if node.args[1].val in self.mapping:
            return [node.args[1]]

        self.simple_traversal(node.args[1:], method_name)

    def log(self, node, method_name):
        """
        Don't check the first argument (e.g. log(type = Name, ...) since the
        compiler catches those.
        """
        self.simple_traversal(node.args[1:], method_name)

    def always_traverse(self, node, method_name):
        return node.args

    mapping = {
        '+': simple_traversal,
        '+=': simple_traversal,

        '-': simple_traversal,
        '-=': simple_traversal,

        '*': simple_traversal,
        '**': simple_traversal,
        '*=': simple_traversal,

        '/': simple_traversal,
        '/=': simple_traversal,

        '%': simple_traversal,
        '%=': simple_traversal,

        '^=': simple_traversal,

        '!': simple_traversal,

        '>': simple_traversal,
        '<': simple_traversal,

        '>=': simple_traversal,
        '<=': simple_traversal,

        '==': simple_traversal,
        '!=': simple_traversal,

        'if': conditional_traversal,
        'elif': conditional_traversal,
        'else': deep_traversal,

        'or': simple_traversal,
        'and': simple_traversal,

        'while': conditional_traversal,
        'for': conditional_traversal,

        'return': simple_traversal,
        '~return': simple_traversal,

        ':': return_type,
        '=': assignment,

        'data': define_data,
        'def': define_method,
        'event': define_event,
        'macro': define_macro,
        # 'extern': define_extern,

        'fun': simple_traversal,
        'log': log,
        'mcopy': simple_traversal,

        'seq': always_traverse,
    }

    def in_scope(self, token, method_name):
        if (token in self.scope[method_name] or
                token in self.data or
                token in self.events or
                token in self.macros or
                token in self.methods):
            return True

        if token in BUILTINS or token in GLOBALS:
            return True

        return False

    def gather_tokens(self, nodes):
        if not nodes:
            return

        if not iterable(nodes):
            nodes = [nodes]

        collected_nodes = flatten(self.traverse_tokens(node) for node in nodes)

        return (set(pair for pair in collected_nodes if pair)
                if collected_nodes
                else None)

    def resolve_token(self, node):
        if isinstance(node, serpent.Token):
            return node.val

        return self.resolve_access(node)

    def traverse_tokens(self, node):
        if node.val == '.':
            return Token('.'.join(self.resolve_token(a) for a in node.args),
                         node.metadata)

        if node.val == ':':
            return self.traverse_tokens(node.args[0])

        if isinstance(node, serpent.Token):
            return (Token(node.val, node.metadata)
                    if self.is_reference(node.val)
                    else None)

        return [self.traverse_tokens(arg) for arg in node.args]

    def traverse(self, node, level=0, method_name=None):
        if not isinstance(node, serpent.Astnode):
            if isinstance(node, serpent.Token):
                self.check(Token(node.val, node.metadata), method_name)

            return

        if self.verbose:
            print('{}{} {}'.format(' ' * level, node.val,
                                   '' if isinstance(node, serpent.Token)
                                   else [n.val for n in node.args]))

        if node.val == 'def':
            method_name = node.args[0].val

        if node.val not in self.mapping:
            if self.is_opcode(node.val) and self.verbose:
                print('{} unknown opcode {}'.format(node.metadata.ln + 1,
                                                    node.val))
        else:
            nodes_to_traverse = self.mapping[node.val](self, node, method_name)

            if nodes_to_traverse:
                for node_to_traverse in nodes_to_traverse:
                    self.traverse(node_to_traverse,
                                  level=level + 1,
                                  method_name=method_name)

    def __init__(self, verbose=False):
        self.verbose = verbose

        self.scope = None

        self.data = None
        self.events = None
        self.macros = None
        self.methods = None
        # self.structs = None

    def lint(self, code):
        self.scope = defaultdict(dict)

        self.data = []
        self.events = []
        self.macros = []
        self.methods = []
        # self.structs = {}

        serpent.compile(code)

        contract_ast = serpent.parse(code)

        self.traverse(contract_ast)

        if self.verbose:
            from pprint import pformat

            print('scope', pformat(self.scope.items()))

            print('data', pformat(self.data))
            print('events', pformat(self.events))
            print('macros', pformat(self.macros))
            print('methods', pformat(self.methods))
            # print('structs', pformat(self.structs))


@click.command()
@click.option('--verbose', is_flag=True)
@click.argument('filename')
def serplint(verbose, filename):
    if verbose:
        print('Linting {}'.format(filename))
        print()

    linter = Linter(verbose=verbose)

    with open(filename, 'r') as f:
        linter.lint(f.read())


if __name__ == '__main__':
    serplint()
