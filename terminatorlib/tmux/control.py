import threading
import subprocess

from gi.repository import Gtk, Gdk

from terminatorlib import tmux
from terminatorlib.tmux import notifications
from terminatorlib.util import dbg


def esc(seq):
    return '\033{}'.format(seq)


KEY_MAPPINGS = {
    Gdk.KEY_BackSpace: '\b',
    Gdk.KEY_Tab: '\t',
    Gdk.KEY_Insert: esc('[2~'),
    Gdk.KEY_Delete: esc('[3~'),
    Gdk.KEY_Page_Up: esc('[5~'),
    Gdk.KEY_Page_Down: esc('[6~'),
    Gdk.KEY_Home: esc('OH'),
    Gdk.KEY_End: esc('OF'),
    Gdk.KEY_Up: esc('[A'),
    Gdk.KEY_Down: esc('[B'),
    Gdk.KEY_Right: esc('[C'),
    Gdk.KEY_Left: esc('[D'),
}
ARROW_KEYS = {
    Gdk.KEY_Up,
    Gdk.KEY_Down,
    Gdk.KEY_Left,
    Gdk.KEY_Right
}


class TmuxControl(object):

    def __init__(self, session_name, notifications_handler):
        self.session_name = session_name
        self.notifications_handler = notifications_handler
        self.tmux = None
        self.output = None
        self.input = None
        self.consumer = None

    def run_command(self, command, marker, cwd=None):
        if self.input:
            self.new_window(cwd=cwd, command=command, marker=marker)
        else:
            self.new_session(cwd=cwd, command=command, marker=marker)

    def new_window(self, cwd=None, command=None, marker=''):
        tmux_command = 'new-window -P -F "{} #D {}"'.format(
            tmux.PANE_ID_RESULT_PREFIX, marker)
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
            '-P', '-F', '{} #D {}'.format(tmux.PANE_ID_RESULT_PREFIX, marker)]
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

        if keyval in KEY_MAPPINGS:
            key = KEY_MAPPINGS[keyval]
            if keyval in ARROW_KEYS and state & Gdk.ModifierType.CONTROL_MASK:
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

    def _run_command(self, command):
        if not self.input:
            dbg('No tmux connection. [command={}]'.format(command))
        else:
            self.input.write('{}\n'.format(command))

    @staticmethod
    def kill_server():
        subprocess.call(['tmux', 'kill-server'])

    def start_notifications_consumer(self):
        self.consumer = threading.Thread(target=self.consume_notifications)
        self.consumer.daemon = True
        self.consumer.start()

    def consume_notifications(self):
        handler = self.notifications_handler
        while self.tmux.poll() is None:
            line = self.output.readline()[:-1]
            if not line:
                continue
            line = line[1:].split(' ')
            marker = line[0]
            line = line[1:]
            notification = notifications.notifications_mappings[marker]()
            notification.consume(line, self.output)
            handler.handle(notification)
w