from gi.repository import GObject

from terminatorlib.util import dbg
from terminatorlib import tmux
from terminatorlib.tmux import layout

notifications_mappings = {}


def notification(cls):
    notifications_mappings[cls.marker] = cls
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
            tmux.PANE_ID_RESULT_PREFIX)

    def is_garbage_collect_panes_result(self):
        return len(self.result) > 0 and self.result[0].startswith(
            tmux.GARBAGE_COLLECT_PANES_PREFIX)

    @property
    def pane_id_and_marker(self):
        _, pane_id, marker = self.result[0].split(' ')
        return pane_id, marker

    @property
    def pane_ids(self):
        result = []
        for line in self.result:
            _, pane_id = line.split(' ')
            result.append(pane_id)
        return result


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
        self.window_layout = layout.parse_layout(window_layout)
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


class NotificationsHandler(object):

    def __init__(self, terminator):
        self.terminator = terminator

    def handle(self, notification):
        try:
            handler_method = getattr(self, 'handle_{}'.format(
                    notification.marker.replace('-', '_')))
            handler_method(notification)
        except AttributeError:
            pass

    def handle_begin(self, notification):
        assert isinstance(notification, Result)
        if notification.error:
            dbg('Request error: {}'.format(notification))
        elif notification.is_pane_id_result():
            pane_id, marker = notification.pane_id_and_marker
            terminal = self.terminator.find_terminal_by_pane_id(marker)
            terminal.pane_id = pane_id
            self.terminator.pane_id_to_terminal[pane_id] = terminal
        elif notification.is_garbage_collect_panes_result():
            pane_ids = set(notification.pane_ids)
            pane_id_to_terminal = self.terminator.pane_id_to_terminal
            removed_pane_ids = [p for p in pane_id_to_terminal.keys()
                                if p not in pane_ids]
            if removed_pane_ids:
                def callback():
                    for pane_id in removed_pane_ids:
                        terminal = pane_id_to_terminal.pop(pane_id, None)
                        if terminal:
                            terminal.close()
                    return False
                GObject.idle_add(callback)

    def handle_output(self, notification):
        assert isinstance(notification, Output)
        pane_id = notification.pane_id
        output = notification.output
        terminal = self.terminator.pane_id_to_terminal.get(pane_id)
        if not terminal:
            return
        terminal.vte.feed(output.decode('string_escape'))

    def handle_layout_change(self, notification):
        assert isinstance(notification, LayoutChange)
        self.terminator.tmux_control.garbage_collect_panes()

    def handle_window_close(self, notification):
        assert isinstance(notification, WindowClose)
        self.terminator.tmux_control.garbage_collect_panes()

    def terminate(self):
        def callback():
            for window in self.terminator.windows:
                window.emit('destroy')
        GObject.idle_add(callback)
