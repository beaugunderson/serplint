#!/usr/bin/env python

from __future__ import print_function

import os
import re
import sys

from collections import defaultdict, Iterable
from contextlib import contextmanager

import click
import serpent

COMPILE_ERROR = 'E100'
PARSE_ERROR = 'E101'
UNDEFINED_VARIABLE = 'E200'
ASSIGNED_TO_ARGUMENT = 'E201'
UNUSED_ARGUMENT = 'W202'
UNREFERENCED_ASSIGNMENT = 'W203'


def iterable(o):
    return isinstance(o, Iterable) and not isinstance(o, basestring)


def flatten(l):
    for el in l:
        if iterable(el):
            for sub in flatten(el):
                yield sub
        else:
            yield el


def fileno(file_or_fd):
    fd = getattr(file_or_fd, 'fileno', lambda: file_or_fd)()

    if not isinstance(fd, int):
        raise ValueError("Expected a file (`.fileno()`) or a file descriptor")

    return fd


@contextmanager
def stdout_redirected(to=os.devnull, stdout=None):
    if stdout is None:
        stdout = sys.stdout

    stdout_fd = fileno(stdout)
    # copy stdout_fd before it is overwritten
    # NOTE: `copied` is inheritable on Windows when duplicating a standard
    # stream
    with os.fdopen(os.dup(stdout_fd), 'wb') as copied:
        stdout.flush()  # flush library buffers that dup2 knows nothing about
        try:
            os.dup2(fileno(to), stdout_fd)  # $ exec >&to
        except ValueError:  # filename
            with open(to, 'wb') as to_file:
                os.dup2(to_file.fileno(), stdout_fd)  # $ exec > to
        try:
            yield stdout  # allow code to be run with the redirected stdout
        finally:
            # restore stdout to its previous value
            # NOTE: dup2 makes stdout_fd inheritable unconditionally
            stdout.flush()
            os.dup2(copied.fileno(), stdout_fd)  # $ exec >&copied


def merged_stderr_stdout():  # $ exec 2>&1
    return stdout_redirected(to=sys.stdout, stdout=sys.stderr)


RE_EXCEPTION = re.compile(
    r'line (?P<line>\d+), char (?P<character>\d+)\): (?P<message>.*)$',
    re.IGNORECASE)

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

    def get_scope(self, method_name, name):
        if method_name in self.scope and name in self.scope[method_name]:
            return self.scope[method_name][name]

    def add_to_scope(self, method_name, token, variable_type):
        if isinstance(token, str):
            name = token
        elif isinstance(token, serpent.Astnode):
            name = self.resolve_access(token)
        elif isinstance(token, serpent.Token):
            name = token.val
        else:
            name = 'unknown'

        if self.get_scope(method_name, name):
            if self.get_scope(method_name, name)['type'] == 'argument':
                self.log_message(
                    token.metadata.ln,
                    token.metadata.ch,
                    ASSIGNED_TO_ARGUMENT,
                    'Assigned a value to an argument "{}"'.format(name))

        self.scope[method_name][name] = {
            'type': variable_type,
            'accessed': False,
            'token': token,
        }

    def reposition(self, line, character):
        """
        Needed because of a bug in how the Serpent AST calculates offset (it
        ignores starting whitespace)
        """
        match = re.match(r'(?P<space>\s+)', self.code_lines[line])
        offset = 0

        if match:
            offset = len(match.group('space'))

        return (line + 1,
                character + 1 + offset)

    def check(self, token, method_name):
        if not self.is_reference(token.name):
            return

        if not self.in_scope(token.name, method_name):
            self.log_message(
                token.metadata.ln,
                token.metadata.ch,
                UNDEFINED_VARIABLE,
                'Undefined variable "{}"'.format(token.name))
        else:
            scope = self.get_scope(method_name, token.name)

            if scope:
                scope['accessed'] = True

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
        assignee = node.args[0]
        assignee_name = self.resolve_access(node)

        if self.is_reference(assignee_name):
            if assignee_name in self.data:
                self.add_to_scope(method_name, assignee, 'data_assignment')
            else:
                self.add_to_scope(method_name, assignee, 'assignment')

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
            return node

        if node.args[0].val == ':':
            return node.args[0].args[0]

        return node.args[0]

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
            self.add_to_scope(name, token, 'argument')

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

    def in_scope(self, name, method_name):
        if (name in self.scope[method_name] or
                name in self.data or
                name in self.events or
                name in self.macros or
                name in self.methods):
            return True

        if name in BUILTINS or name in GLOBALS:
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

        if self.debug:
            print('{}{} {}'.format(' ' * level, node.val,
                                   '' if isinstance(node, serpent.Token)
                                   else [n.val for n in node.args]))

        if node.val == 'def':
            method_name = node.args[0].val

        if node.val not in self.mapping:
            if self.is_opcode(node.val) and self.debug:
                print('{} unknown opcode {}'.format(node.metadata.ln + 1,
                                                    node.val))
        else:
            nodes_to_traverse = self.mapping[node.val](self, node, method_name)

            if nodes_to_traverse:
                for node_to_traverse in nodes_to_traverse:
                    self.traverse(node_to_traverse,
                                  level=level + 1,
                                  method_name=method_name)

    def log_message(self, line, character, error, message, reposition=True):
        """
        Log a linter message to stderr, ignoring duplicates.
        """
        if error[0] == 'E':
            formatted_code = click.style(error, fg='red')
        else:
            formatted_code = click.style(error, fg='yellow')

        if reposition:
            line, character = self.reposition(line, character)

        message = '{}:{}:{} {} {}'.format(self.filename,
                                          line,
                                          character,
                                          formatted_code,
                                          message)

        if message in self.logged_messages:
            return

        self.exit_code = 1
        self.logged_messages.append(message)

        click.echo(message)

    def __init__(self, input_file, verbose=False, debug=False):
        self.code = input_file.read()
        self.code_lines = self.code.splitlines()

        self.filename = input_file.name

        self.verbose = verbose
        self.debug = debug

        self.exit_code = None

        self.logged_messages = None
        self.scope = None

        self.data = None
        self.events = None
        self.macros = None
        self.methods = None
        # self.structs = None

    def lint(self):
        self.exit_code = 0

        self.logged_messages = []
        self.scope = defaultdict(dict)

        self.data = []
        self.events = []
        self.macros = []
        self.methods = []
        # self.structs = {}

        # ('Error (file "main", line 2, char 12): Invalid argument count ...
        try:
            # override stdout since serpent tries to print the exception itself
            with stdout_redirected(), merged_stderr_stdout():
                serpent.compile(self.code)
        except Exception as e:
            match = RE_EXCEPTION.search(e.args[0])

            if match:
                self.log_message(match.group('line'),
                                 match.group('character'),
                                 COMPILE_ERROR,
                                 match.group('message'),
                                 reposition=False)
            else:
                click.echo('Exception: {}'.format(e.args[0]), err=True)

                sys.exit(1)

        # ('Error (file "main", line 2, char 12): Invalid argument count ...
        try:
            # override stdout since serpent tries to print the exception itself
            with stdout_redirected(), merged_stderr_stdout():
                contract_ast = serpent.parse(self.code)
        except Exception as e:
            match = RE_EXCEPTION.search(e.args[0])

            if match:
                self.log_message(match.group('line'),
                                 match.group('character'),
                                 PARSE_ERROR,
                                 match.group('message'),
                                 reposition=False)
            else:
                print('Exception: {}'.format(e.args[0]), err=True)

            sys.exit(1)

        self.traverse(contract_ast)

        for method, variables in self.scope.items():
            if not method:
                continue

            for variable, metadata in variables.items():
                if not metadata['accessed']:
                    if metadata['type'] == 'argument':
                        self.log_message(
                            metadata['token'].metadata.ln,
                            metadata['token'].metadata.ch,
                            UNUSED_ARGUMENT,
                            'Unused argument "{}"'.format(variable))
                    elif metadata['type'] == 'assignment':
                        self.log_message(
                            metadata['token'].metadata.ln,
                            metadata['token'].metadata.ch,
                            UNREFERENCED_ASSIGNMENT,
                            'Unreferenced assignment "{}"'.format(variable))

        if self.debug:
            from pprint import pformat

            click.echo('scope ' + pformat(self.scope.items()))

            click.echo('data ' + pformat(self.data))
            click.echo('events ' + pformat(self.events))
            click.echo('macros ' + pformat(self.macros))
            click.echo('methods ' + pformat(self.methods))
            # click.echo('structs', pformat(self.structs))

        return self.exit_code


@click.command()
@click.option('--verbose', '-v', is_flag=True)
@click.option('--debug', '-d', is_flag=True)
@click.version_option()
@click.argument('input_file', type=click.File('rb'))
def serplint(verbose, debug, input_file):
    if verbose:
        print('Linting {}'.format(input_file.name))
        print()

    linter = Linter(input_file, verbose=verbose, debug=debug)
    exit_code = linter.lint()

    sys.exit(exit_code)


# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    serplint()
