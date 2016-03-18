def parse_layout(layout):
    layout = layout.split(',')
    layout = ','.join(layout[1:])

    def parse(consumed):
        result = []
        while True:
            sep = layout[consumed:].index(',')
            size = layout[consumed:consumed + sep]
            width, height = size.split('x')
            consumed += 1 + len(size)
            sep = layout[consumed:].index(',')
            x = layout[consumed:consumed + sep]
            consumed += 1 + len(x)
            seps = [layout[consumed:].find(c) for c in ',{[']
            sep = min(s for s in seps if s != -1)
            y = layout[consumed:consumed + sep]
            consumed += 1 + len(y)
            if layout[consumed - 1] == '[':
                panes, consumed = parse(consumed)
                container = Vertical(width, height, x, y, panes)
            elif layout[consumed - 1] == '{':
                panes, consumed = parse(consumed)
                container = Horizontal(width, height, x, y, panes)
            else:
                seps = [layout[consumed:].find(c) for c in ',}]']
                seps = [s for s in seps if s != -1]
                if not seps:
                    pane_id = layout[consumed:]
                    consumed = len(layout)
                else:
                    sep = min(seps)
                    pane_id = layout[consumed: consumed + sep]
                    consumed += 1 + len(pane_id)
                container = Pane(width, height, x, y, pane_id)
            result.append(container)
            if consumed == len(layout) or layout[consumed - 1] in ']}':
                return result, consumed
    return parse(consumed=0)[0][0]


class Container(object):

    def __init__(self, width, height, x, y):
        self.width = width
        self.height = height
        self.x = x
        self.y = y

    def __str__(self):
        return (
            '{}[width={}, height={}, x={}, y={}, {}]'
            .format(self.__class__.__name__,
                    self.width, self.height, self.x, self.y,
                    self._child_str()))

    __repr__ = __str__

    def _child_str(self):
        raise NotImplementedError()


class Pane(Container):

    def __init__(self, width, height, x, y, pane_id):
        super(Pane, self).__init__(width, height, x, y)
        self.pane_id = pane_id

    def _child_str(self):
        return 'pane_id={}'.format(self.pane_id)


class Vertical(Container):

    def __init__(self, width, height, x, y, panes):
        super(Vertical, self).__init__(width, height, x, y)
        self.panes = panes

    def _child_str(self):
        return 'panes={}'.format(self.panes)


class Horizontal(Container):

    def __init__(self, width, height, x, y, panes):
        super(Horizontal, self).__init__(width, height, x, y)
        self.panes = panes

    def _child_str(self):
        return 'panes={}'.format(self.panes)
