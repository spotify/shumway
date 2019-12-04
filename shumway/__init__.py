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

import requests
import six


__author__ = 'Lynn Root'
__version__ = '1.1.0'
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

    def as_map(self):
        """Create a map of data"""
        return {
            'key': self.key,
            'attributes': self._attributes,
            'value': self.value,
            'type': 'metric',
            'tags': self._tags
        }

    def flush(self, func):
        """Create a map of data and pass it to another function"""
        func(self.as_map())


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
    def __init__(self, default_key, ffwd_host=FFWD_IP, ffwd_port=FFWD_PORT,
                 ffwd_path=None, default_attributes=None, use_http=False):
        self._metrics = {}
        self._default_key = default_key
        self._default_attributes = copy.deepcopy(default_attributes)
        self._sender = _HTTPSender(ffwd_host, ffwd_port, ffwd_path) \
            if use_http else _UDPSender(ffwd_host, ffwd_port)

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
        self._sender.send(self._metrics)

    def flush_single(self, metric):
        """Send a metric to FFWD."""
        self._sender.send_single(metric)

    def __contains__(self, metric):
        return metric in self._metrics


class _UDPSender:
    def __init__(self, ffwd_host, ffwd_port):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ffwd_address = (ffwd_host, ffwd_port)

    def send(self, metrics):
        for metric in six.itervalues(metrics):
            self._sock.sendto(
                json.dumps(metric.as_map()).encode('utf-8'), self._ffwd_address)

    def send_single(self, metric):
        self.send({metric.key: metric})


class _HTTPSender:
    def __init__(self, ffwd_host, ffwd_port, ffwd_path):
        if not ffwd_host.startswith("http") and ffwd_port == 443:
            ffwd_host = "https://" + ffwd_host
        elif not ffwd_host.startswith("http"):
            ffwd_host = "http://" + ffwd_host

        self._ffwd_url = "{}:{}".format(ffwd_host, ffwd_port)
        self._ffwd_url = self._ffwd_url + ffwd_path \
            if ffwd_path is not None else self._ffwd_url

    def send(self, metrics):
        metrics_resolved = [self._convert_metric_to_http_payload(m)
                            for m in six.itervalues(metrics)]
        metrics_payload = {
            'points': metrics_resolved
        }

        requests.post(self._ffwd_url, json=metrics_payload).raise_for_status()

    def send_single(self, metric):
        self.send({metric.key: metric})

    def _convert_metric_to_http_payload(self, metric):
        metrics_as_map = metric.as_map()

        return {
            'key': metrics_as_map['key'],
            'tags': metrics_as_map['attributes'],
            'resource': {},
            'value': metrics_as_map['value'],
            'timestamp': int(time.time() * 1000.0),
        }
