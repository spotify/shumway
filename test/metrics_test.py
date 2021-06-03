# -*- coding: utf-8 -*-
#
# Copyright 2015-2017 Spotify AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import json
import socket

import mock
import six
import unittest2

import shumway


def patcher(classes, autospec=True):
    PatchedClass = collections.namedtuple('PatchedClass',
                                          ['patcher',
                                           'mock_object',
                                           'mock_instance'])
    patched = {}
    for objectpath in classes:
        patcherer = mock.patch(objectpath)
        mock_object = patcherer.start()
        mock_instance = mock_object.return_value
        patched[objectpath] = PatchedClass(patcher=patcherer,
                                           mock_object=mock_object,
                                           mock_instance=mock_instance)
    return patched


def list_of_mocks(target, quantity):
    mocks = []
    for _ in six.moves.xrange(quantity):
        class_ = mock.patch(target, autospec=True)
        instance = class_.start()
        mocks.append(instance)
    return mocks


class TimerTest(unittest2.TestCase):

    @mock.patch('shumway.time.time')
    def test_timer(self, time):
        time.side_effect = [0, 1]
        timer = shumway.Timer('timer', 'key', {'test': 'test'})
        with timer:
            pass
        self.assertEqual(timer.value, 1000000000.0)

    @mock.patch('shumway.time.time')
    def test_timer_tags(self, time):
        time.side_effect = [0, 1]
        timer = shumway.Timer('timer',
                              'key',
                              {'test': 'test'},
                              {'res1': 'test'},
                              ['test'])
        with timer:
            pass
        self.assertEqual(timer.value, 1000000000.0)

    @mock.patch('shumway.time.time')
    def test_flush(self, time):
        send_metric = mock.Mock()
        time.side_effect = [0, 1]
        timer = shumway.Timer('timer', 'key')
        timer.flush(send_metric)
        send_metric.assert_called_once_with({
            'tags': [],
            'value': None,
            'attributes': {'what': 'timer', 'unit': 'ns'},
            'resources': {},
            'key': 'key',
            'type': 'metric'})


class CounterTest(unittest2.TestCase):
    def test_incr_once(self):
        C = shumway.Counter('test', 'key')
        C.incr()
        self.assertEqual(C.value, 1)

    def test_incr_twice(self):
        C = shumway.Counter('test', 'key')
        C.incr()
        C.incr()
        self.assertEqual(C.value, 2)

    def test_incr_by_value(self):
        C = shumway.Counter('test', 'key')
        C.incr(3)
        self.assertEqual(C.value, 3)

    def test_flush(self):
        send_metric = mock.Mock()
        C = shumway.Counter('test', 'key')
        C.incr()
        C.flush(send_metric)
        send_metric.assert_called_once_with({
            'key': 'key',
            'attributes': {'what': 'test'},
            'resources': {},
            'value': 1,
            'tags': [],
            'type': 'metric'})

    def test_flush_with_attributes(self):
        send_metric = mock.Mock()
        C = shumway.Counter('test', 'key', attributes={'k': 'v'})
        C.incr()
        C.flush(send_metric)
        send_metric.assert_called_once_with({
            'key': 'key',
            'attributes': {'what': 'test', 'k': 'v'},
            'resources': {},
            'value': 1,
            'tags': [],
            'type': 'metric'})

    def test_flush_with_tags(self):
        send_metric = mock.Mock()
        C = shumway.Counter('test', 'key', tags=['test::tag'])
        C.incr()
        C.flush(send_metric)
        send_metric.assert_called_once_with({
            'key': 'key',
            'attributes': {'what': 'test'},
            'resources': {},
            'value': 1,
            'tags': ['test::tag'],
            'type': 'metric'})

    def test_flush_with_resources(self):
        send_metric = mock.Mock()
        C = shumway.Counter('test', 'key', attributes=None,
                            resources={'res1': 'value'})
        C.incr()
        C.flush(send_metric)
        send_metric.assert_called_once_with({
            'key': 'key',
            'attributes': {'what': 'test'},
            'value': 1,
            'type': 'metric',
            'tags': [],
            'resources': {'res1': 'value'}})

    def test_intial_value(self):
        C = shumway.Counter('test', 'key', value=4)
        C.incr(4)
        self.assertEqual(C.value, 8)


class MetricRelayTest(unittest2.TestCase):
    def setUp(self):
        self.patched = patcher(
            ['shumway.socket.socket', 'shumway.requests'])

    def tearDown(self):
        for patched in six.itervalues(self.patched):
            patched.patcher.stop()

    def test_emit(self):
        sock = self.patched[
            'shumway.socket.socket'].mock_instance
        mr = shumway.MetricRelay('key')
        attr = {'pod': 'gew1'}
        tags = ['cool-metric']
        res = {'res1': 'value'}

        mr.emit('one_time_metric', 22,
                attributes=attr,
                resources=res,
                tags=tags)

        metric = {'key': 'key',
                  'attributes': {'what': 'one_time_metric', 'pod': 'gew1'},
                  'value': 22,
                  'type': 'metric',
                  'tags': ['cool-metric'],
                  'resources': {'res1': 'value'}}
        sock.sendto.assert_called_once_with(
            json.dumps(metric).encode('utf-8'), mr._sender._ffwd_address)

    def test_incr_and_send(self):
        sock = self.patched[
            'shumway.socket.socket'].mock_instance

        mr = shumway.MetricRelay('key')
        mr.incr('test')
        mr.incr('test')
        mr.flush()

        metric = {'key': 'key',
                  'attributes': {'what': 'test'},
                  'value': 2,
                  'type': 'metric',
                  'tags': [],
                  'resources': {}}
        sock.sendto.assert_called_once_with(
            json.dumps(metric).encode('utf-8'), mr._sender._ffwd_address)

    def test_incr_and_send_with_default_attributes(self):
        sock = self.patched[
            'shumway.socket.socket'].mock_instance

        mr = shumway.MetricRelay('key', default_attributes=dict(foo='bar'))
        mr.incr('test')
        mr.incr('test')
        mr.flush()

        metric = {'key': 'key',
                  'attributes': {'what': 'test',
                                 'foo': 'bar'},
                  'value': 2,
                  'type': 'metric',
                  'tags': [],
                  'resources': {}}
        sock.sendto.assert_called_once_with(
            json.dumps(metric).encode('utf-8'), mr._sender._ffwd_address)

    @mock.patch('shumway.time', autospec=True)
    def test_send_via_http(self, time):
        time.time.return_value = 1
        requests = self.patched[
            'shumway.requests'].mock_object

        mr = shumway.MetricRelay('key',
                                 ffwd_host="http://metrics.com",
                                 ffwd_port=8080,
                                 ffwd_path="/v1/api",
                                 use_http=True)
        mr.incr('test')
        mr.incr('test')
        mr.flush()

        metric_payload = {'points': [
            {'key': 'key',
             'tags': {'what': 'test'},
             'resource': {},
             'value': 2,
             'timestamp': 1000
             }
        ]}

        requests.post.assert_called_once_with(
            "http://metrics.com:8080/v1/api", json=metric_payload)

    def test_custom_counter(self):
        sock = self.patched[
            'shumway.socket.socket'].mock_instance

        mr = shumway.MetricRelay('key')
        mr.set_counter(
            'test', shumway.Counter('test', 'key',
                                    attributes={'k': 'v'},
                                    tags=['foo::bar']))
        mr.incr('test')

        mr.flush()

        metric = {'key': 'key',
                  'attributes': {'what': 'test', 'k': 'v'},
                  'value': 1,
                  'type': 'metric',
                  'tags': ['foo::bar'],
                  'resources': {}}
        sock.sendto.assert_called_once_with(
            json.dumps(metric).encode('utf-8'), mr._sender._ffwd_address)

    @mock.patch('shumway.Timer', autospec=True)
    def test_timer(self, timer_init):
        timer_init.return_value.as_dict.return_value = {}
        sock = self.patched[
            'shumway.socket.socket'].mock_instance

        mr = shumway.MetricRelay('key')
        mr.timer('foo-timer')
        mr.flush()

        timer_init.assert_called_once_with('foo-timer', key='key',
                                           attributes=None, resources=None)
        sock.sendto.assert_called_once()

    @mock.patch('shumway.Timer', autospec=True)
    def test_timer_with_default_attributes(self, timer_init):
        timer_init.return_value.as_dict.return_value = {}
        sock = self.patched[
            'shumway.socket.socket'].mock_instance

        attrs = dict(foo='bar')
        mr = shumway.MetricRelay('key', default_attributes=attrs)
        mr.timer('foo-timer')
        mr.flush()

        timer_init.assert_called_once_with('foo-timer', key='key',
                                           attributes=attrs, resources=None)
        sock.sendto.assert_called_once()

    @mock.patch('shumway.Timer', autospec=True)
    def test_getting_timer_twice(self, timer_init):
        timer_init.return_value.as_dict.return_value = {}
        sock = self.patched[
            'shumway.socket.socket'].mock_instance

        mr = shumway.MetricRelay('key')
        timer = mr.timer('foo-timer')
        same_timer = mr.timer('foo-timer')

        mr.flush()

        self.assertEqual(timer, same_timer)
        timer_init.assert_called_once_with('foo-timer', key='key',
                                           attributes=None, resources=None)
        sock.sendto.assert_called_once()

    def test_custom_timer(self):
        sock = self.patched[
            'shumway.socket.socket'].mock_instance

        timer = mock.Mock(shumway.Timer)
        timer.as_dict.return_value = {}

        mr = shumway.MetricRelay('key')
        mr.set_timer('key', timer)
        mr.flush()

        sock.sendto.assert_called_once()

    def test_creates_UDP_socket(self):
        sock = self.patched['shumway.socket.socket'].mock_object

        mr = shumway.MetricRelay('key')
        mr.incr('test')
        mr.flush()

        sock.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)

    def test_in_operator(self):
        mr = shumway.MetricRelay('key')
        self.assertNotIn('foo', mr)
        mr.incr('foo')
        self.assertIn('foo', mr)
