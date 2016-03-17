import threading
import subprocess

from gi.repository import Gtk, Gdk

PANE_ID_RESULT_PREFIX = '|||'

mappings = {}


def notification(cls):
    mappings[cls.marker] = cls
    return cls


class Notification(object):

    marker = 'undefined'
    attributes = []

    def consume(self, line, out):
        pass

    def __str__(self):
        attributes = ['{}="{}"'.format(attribute, getattr(self, attribute, ''))
                      for attribute in self.attributes]
        return '{}[{}]'.format(self.marker, ', '.join(attributes))


@notification
class Result(Notification):

    marker = 'begin'
    attributes = ['begin_timestamp', 'code', 'result', 'end_timestamp',
                  'error']

    def consume(self, line, out):
        timestamp, code, _ = line
        self.begin_timestamp = timestamp
        self.code = code
        result = []
        line = out.readline()[:-1]
        while not (line.startswith('%end') or line.startswith('%error')):
            result.append(line)
            line = out.readline()[:-1]
        self.result = result
        end, timestamp, code, _ = line.split(' ')
        self.end_timestamp = timestamp
        self.error = end == '%error'

    def is_pane_id_result(self):
        return len(self.result) == 1 and self.result[0].startswith(
            PANE_ID_RESULT_PREFIX)

    @property
    def pane_id_and_marker(self):
        _, pane_id, marker = self.result[0].split(' ')
        return pane_id, marker


@notification
class Exit(Notification):

    marker = 'exit'
    attributes = ['reason']

    def consume(self, line, *args):
        self.reason = line[0] if line else None


@notification
class LayoutChange(Notification):

    marker = 'layout-change'
    attributes = ['window_id', 'window_layout', 'window_visible_layout',
                  'window_flags']

    def consume(self, line, *args):
        # window_id, window_layout, window_visible_layout, window_flags = line
        window_id, window_layout = line
        self.window_id = window_id
        self.window_layout = window_layout
        # self.window_visible_layout = window_visible_layout
        # self.window_flags = window_flags


@notification
class Output(Notification):

    marker = 'output'
    attributes = ['pane_id', 'output']

    def consume(self, line, *args):
        pane_id = line[0]
        output = ' '.join(line[1:])
        self.pane_id = pane_id
        self.output = output


@notification
class SessionChanged(Notification):

    marker = 'session-changed'
    attributes = ['session_id', 'session_name']

    def consume(self, line, *args):
        session_id, session_name = line
        self.session_id = session_id
        self.session_name = session_name


@notification
class SessionRenamed(Notification):

    marker = 'session-renamed'
    attributes = ['session_id', 'session_name']

    def consume(self, line, *args):
        session_id, session_name = line
        self.session_id = session_id
        self.session_name = session_name


@notification
class SessionsChanged(Notification):

    marker = 'sessions-changed'
    attributes = []


@notification
class UnlinkedWindowAdd(Notification):

    marker = 'unlinked-window-add'
    attributes = ['window_id']

    def consume(self, line, *args):
        window_id, = line
        self.window_id = window_id


@notification
class WindowAdd(Notification):

    marker = 'window-add'
    attributes = ['window_id']

    def consume(self, line, *args):
        window_id, = line
        self.window_id = window_id


@notification
class WindowClose(Notification):

    marker = 'window-close'
    attributes = ['window_id']

    def consume(self, line, *args):
        window_id, = line
        self.window_id = window_id


@notification
class WindowRenamed(Notification):

    marker = 'window-renamed'
    attributes = ['window_id', 'window_name']

    def consume(self, line, *args):
        window_id, window_name = line
        self.window_id = window_id
        self.window_name = window_name


def esc(seq):
    return '\033{}'.format(seq)


class TmuxControl(object):

    def __init__(self, session_name, notifications_handler):
        self.session_name = session_name
        self.notifications_handler = notifications_handler
        self.tmux = None
        self.output = None
        self.input = None
        self.consumer = None

        raw_mappings = {
            'BackSpace': '\b',
            'Tab': '\t',
            'Insert': esc('[2~'),
            'Delete': esc('[3~'),
            'Page_Up': esc('[5~'),
            'Page_Down': esc('[6~'),
            'Home': esc('OH'),
            'End': esc('OF'),
            'Up': esc('[A'),
            'Down': esc('[B'),
            'Right': esc('[C'),
            'Left': esc('[D'),
        }
        self.mappings = {Gdk.keyval_from_name(name): value
                         for name, value in raw_mappings.items()}
        self.arrows = {Gdk.keyval_from_name(name)
                       for name in ['Up', 'Down', 'Right', 'Left']}

    def run_command(self, command, marker, cwd=None):
        if self.input:
            self.new_window(cwd=cwd, command=command, marker=marker)
        else:
            self.new_session(cwd=cwd, command=command, marker=marker)

    def new_window(self, cwd=None, command=None, marker=''):
        tmux_command = 'new-window -P -F "{} #D {}"'.format(
            PANE_ID_RESULT_PREFIX, marker)
        # TODO: fix (getting None for pid, e.g. /proc/None/cwd)
        # if cwd:
        #     tmux_command += ' -c "{}"'.format(cwd)
        if command:
            tmux_command += ' "{}"'.format(command)
        self._run_command(tmux_command)

    def new_session(self, cwd=None, command=None, marker=''):
        self.kill_server()

        popen_command = [
            'tmux', '-2', '-C', 'new-session', '-s', self.session_name,
            '-P', '-F', '{} #D {}'.format(PANE_ID_RESULT_PREFIX, marker)]
        if cwd:
            popen_command += ['-c', cwd]
        if command:
            popen_command.append(command)
        self.tmux = subprocess.Popen(popen_command,
                                     stdout=subprocess.PIPE,
                                     stdin=subprocess.PIPE)
        self.input = self.tmux.stdin
        self.output = self.tmux.stdout
        self.start_notifications_consumer()

    def refresh_client(self, width, height):
        self._run_command('refresh-client -C {},{}'.format(width, height))

    def send_keypress(self, event, pane_id):
        keyval = event.keyval
        state = event.state

        if keyval in self.mappings:
            key = self.mappings[keyval]
            if keyval in self.arrows and state & Gdk.ModifierType.CONTROL_MASK:
                key = '{}1;5{}'.format(key[:2], key[2:])
        else:
            key = event.string

        if state & Gdk.ModifierType.MOD1_MASK:
            # Hack to have CTRL+SHIFT+Alt PageUp/PageDown/Home/End
            # work without these silly [... escaped characters
            if state & (Gdk.ModifierType.CONTROL_MASK |
                        Gdk.ModifierType.SHIFT_MASK):
                return
            else:
                key = esc(key)

        if key == ';':
            key = '\\;'

        self.send_content(key, pane_id)

    def send_content(self, content, pane_id):
        quote = '"' if "'" in content else "'"
        self._run_command("send-keys -t {} -l {}{}{}".format(
                pane_id, quote, content, quote))

    @staticmethod
    def kill_server():
        subprocess.call(['tmux', 'kill-server'])

    def start_notifications_consumer(self):
        callback = self.notifications_handler

        def target():
            for notification in self.consume_notifications():
                callback(notification)
        self.consumer = threading.Thread(target=target)
        self.consumer.daemon = True
        self.consumer.start()

    def consume_notifications(self):
        while self.tmux.poll() is None:
            line = self.output.readline()[:-1]
            if not line:
                continue
            line = line[1:].split(' ')
            marker = line[0]
            line = line[1:]
            notification = mappings[marker]()
            notification.consume(line, self.output)
            yield notification

    def _run_command(self, command):
        self.input.write('{}\n'.format(command))
