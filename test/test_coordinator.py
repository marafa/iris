from gevent import spawn, monkey, sleep, socket
monkey.patch_all()

import pytest  # noqa
from iris.sender.coordinator import Coordinator, NonClusterCoordinator  # noqa

zk_address = ('localhost', 2181)
zk_url = '%s:%s' % zk_address


class TestFailover():
    @classmethod
    def setup_class(cls):
        cls.instances = {}

    @classmethod
    def teardown_class(cls):
        for instance in cls.instances.itervalues():
            instance.leave_cluster()

    def test_failover(self):
        # If we can't connect to zk, skip
        try:
            sock = socket.socket()
            sock.connect(zk_address)
            sock.close()
        except socket.error:
            pytest.skip('Skipping this test as ZK server is not running/reachable.')

        # Create an initial instance which should become master
        self.instances['c1'] = Coordinator(zk_url, 'testinstance', '1001', True)
        spawn(self.instances['c1'].update_forever)
        sleep(3)
        assert self.instances['c1'].am_i_master()

        # Make another instance which should become slave
        self.instances['c2'] = Coordinator(zk_url, 'testinstance', '1002', True)
        spawn(self.instances['c2'].update_forever)
        sleep(3)
        assert self.instances['c2'].am_i_master() is False

        # Verify it became slave
        sleep(3)
        assert self.instances['c1'].slave_count == 1
        assert self.instances['c1'].slaves.next() == (u'testinstance', 1002)

        # Verify API can see these instances
        self.instances['api'] = Coordinator(zk_url, None, None, False)
        assert self.instances['api'].get_current_master() == (u'testinstance', 1001)
        assert (u'testinstance', 1002) in self.instances['api'].get_current_slaves()

        # Kill off first master and see if slave becomes master with no slaves
        self.instances['c1'].leave_cluster()
        sleep(5)
        assert self.instances['c2'].am_i_master()
        assert self.instances['c2'].slave_count == 0

        # Start old master again and see if it becomes a slave
        self.instances['c1'] = Coordinator(zk_url, 'testinstance', '1001', True)
        spawn(self.instances['c1'].update_forever)
        sleep(5)
        assert self.instances['c1'].am_i_master() is False

        # It should show up as a slave to self.instances['c2'] which is now master
        assert self.instances['c2'].am_i_master()
        assert self.instances['c2'].slave_count == 1
        assert self.instances['c2'].slaves.next() == (u'testinstance', 1001)


def test_non_cluster():
    assert NonClusterCoordinator(False, []).am_i_master() is False

    master_without_slaves = NonClusterCoordinator(True, [])
    assert master_without_slaves.am_i_master()
    assert master_without_slaves.slave_count == 0

    master_with_slaves = NonClusterCoordinator(True, [{'host': 'testinstance', 'port': 1001}, {'host': 'testinstance', 'port': 1002}])
    assert master_with_slaves.am_i_master()
    assert master_with_slaves.slave_count == 2

    slaves = master_with_slaves.slaves
    assert slaves.next() == ('testinstance', 1001)
    assert slaves.next() == ('testinstance', 1002)
    assert slaves.next() == ('testinstance', 1001)
    assert slaves.next() == ('testinstance', 1002)
