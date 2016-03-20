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
                children, consumed = parse(consumed)
                container = Vertical(width, height, x, y, children)
            elif layout[consumed - 1] == '{':
                children, consumed = parse(consumed)
                container = Horizontal(width, height, x, y, children)
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
                container = Pane(width, height, x, y, '%{}'.format(pane_id))
            result.append(container)
            if consumed == len(layout) or layout[consumed - 1] in ']}':
                return result, consumed
    return parse(consumed=0)[0][0]


def convert_to_terminator_layout(window_layouts):
    assert len(window_layouts) > 0
    result = {}
    pane_index = 0
    window_name = 'window0'
    parent_name = window_name
    result[window_name] = {
        'type': 'Window',
        'parent': ''
    }
    if len(window_layouts) > 1:
        notebook_name = 'notebook0'
        result[notebook_name] = {
            'type': 'Notebook',
            'parent': parent_name
        }
        parent_name = notebook_name
    order = 0
    for window_layout in window_layouts:
        converter = _get_converter(window_layout)
        pane_index, order = converter(
            result, parent_name, window_layout, pane_index, order)
    return result


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

    def __init__(self, width, height, x, y, children):
        super(Vertical, self).__init__(width, height, x, y)
        self.children = children

    def _child_str(self):
        return 'children={}'.format(self.children)


class Horizontal(Container):

    def __init__(self, width, height, x, y, children):
        super(Horizontal, self).__init__(width, height, x, y)
        self.children = children

    def _child_str(self):
        return 'children={}'.format(self.children)


def _covert_pane_to_terminal(result, parent_name, pane, pane_index, order):
    assert isinstance(pane, Pane)
    terminal = _convert(parent_name, 'Terminal', pane, order)
    order += 1
    terminal['tmux']['pane_id'] = pane.pane_id
    result['terminal{}'.format(pane.pane_id[1:])] = terminal
    return pane_index, order


def _convert_vertical_to_vpane(result, parent_name, vertical_or_children,
                               pane_index, order):
    return _convert_container_to_terminator_pane(
            result, parent_name, vertical_or_children, pane_index, Vertical,
            order)


def _convert_horizontal_to_hpane(result, parent_name, horizontal_or_children,
                                 pane_index, order):
    return _convert_container_to_terminator_pane(
            result, parent_name, horizontal_or_children, pane_index,
            Horizontal, order)


def _convert_container_to_terminator_pane(result, parent_name,
                                          container_or_children,
                                          pane_index, pane_type,
                                          order):
    terminator_type = 'VPaned' if issubclass(pane_type, Vertical) else 'HPaned'
    if isinstance(container_or_children, pane_type):
        container = container_or_children
        pane = _convert(parent_name, terminator_type, container_or_children,
                        order)
        order += 1
        children = container.children
    else:
        children = container_or_children
        if len(children) == 1:
            child = children[0]
            child_converter = _get_converter(child)
            return child_converter(result, parent_name, child, pane_index,
                                   order)
        pane = {
            'type': terminator_type,
            'parent': parent_name
        }
    pane_name = 'pane{}'.format(pane_index)
    result[pane_name] = pane
    parent_name = pane_name
    pane_index += 1
    child1 = children[0]
    child1_converter = _get_converter(child1)
    pane_index, order = child1_converter(result, parent_name, child1,
                                         pane_index, order)
    pane_index, order = _convert_vertical_to_vpane(result, parent_name,
                                                   children[1:],
                                                   pane_index,
                                                   order)
    return pane_index, order


converters = {
    Pane: _covert_pane_to_terminal,
    Vertical: _convert_vertical_to_vpane,
    Horizontal: _convert_horizontal_to_hpane
}


def _get_converter(container):
    try:
        return converters[type(container)]
    except KeyError:
        raise ValueError('Illegal window layout: {}'.format(container))


def _convert(parent_name, type_name, container, order):
    assert isinstance(container, Container)
    return {
        'type': type_name,
        'parent': parent_name,
        'order': order,
        'tmux': {
            'width': container.width,
            'height': container.height,
            'x': container.x,
            'y': container.y
        }
    }
