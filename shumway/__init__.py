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

import copy
import json
import socket
import time

import six


__author__ = 'Lynn Root'
__version__ = '1.0.0'
__license__ = 'Apache 2.0'
__email__ = 'lynn@spotify.com'
__description__ = 'Micro metrics library for ffwd'
__uri__ = 'https://github.com/spotify/shumway'


FFWD_IP = '127.0.0.1'
FFWD_PORT = 19000
GIGA_UNIT = 1E9


class Meter(object):
    """A single metric with updateable value (no local aggregation)."""
    def __init__(self, what, key, attributes=None, tags=None, value=0):
        self.value = value
        self.key = key
        self._attributes = {'what': what}
        if attributes is not None:
            self._attributes.update(attributes)
        if tags is None:
            self._tags = []
        else:
            self._tags = tags

    def update(self, value):
        self.value = value

    def flush(self, func):
        """Create a map of data and pass it to another function"""
        func({
            'key': self.key,
            'attributes': self._attributes,
            'value': self.value,
            'type': 'metric',
            'tags': self._tags
        })


class Counter(Meter):
    """Keep track of an incrementally increasing metric."""

    def incr(self, value=1):
        self.update(self.value + value)


class Timer(Meter):
    """Time the duration of running something"""
    def __init__(self, what, key, attributes=None, tags=None):
        Meter.__init__(self, what, key, attributes, tags)
        self._attributes.update({'unit': 'ns'})
        self._start = None
        self.value = None

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, *args):
        self.update((time.time() - self._start) * GIGA_UNIT)


class MetricRelay(object):
    """Create and send metrics"""
    def __init__(self, default_key, ffwd_ip=FFWD_IP, ffwd_port=FFWD_PORT,
                 default_attributes=None):
        self._metrics = {}
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._default_key = default_key
        self._ffwd_address = (ffwd_ip, ffwd_port)

        self._default_attributes = copy.deepcopy(default_attributes)

    def emit(self, metric, value, attributes=None, tags=None):
        """Emit one-time metric that does not need to be stored."""
        one_time_metric = Meter(metric, key=self._default_key,
                                value=value, attributes=attributes, tags=tags)
        self.flush_single(one_time_metric)

    def incr(self, metric, value=1):
        """Increment a metric, creates it if new"""
        if metric in self._metrics:
            counter = self._metrics[metric]
        else:
            counter = Counter(metric, key=self._default_key,
                              attributes=self._default_attributes)
            self._metrics[metric] = counter
        counter.incr(value)

    def timer(self, metric):
        timer_metric = 'timer-{}'.format(metric)
        if timer_metric in self._metrics:
            timer = self._metrics[timer_metric]
        else:
            timer = Timer(metric, key=self._default_key,
                          attributes=self._default_attributes)
            self._metrics[timer_metric] = timer
        return timer

    def set_counter(self, metric, counter):
        self._metrics[metric] = counter

    def set_timer(self, metric, timer):
        self._metrics['timer-{}'.format(metric)] = timer

    def flush(self):
        """Send all metrics to FFWD"""
        for metric in six.itervalues(self._metrics):
            self.flush_single(metric)

    def flush_single(self, metric):
        """Send a metric to FFWD."""
        metric.flush(self._sendto)

    def _sendto(self, metric):
        self._sock.sendto(
            json.dumps(metric).encode('utf-8'), self._ffwd_address)

    def __contains__(self, metric):
        return metric in self._metrics
