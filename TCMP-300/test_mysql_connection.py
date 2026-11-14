"""Regression for a disconnected socket also failing during rollback."""
import unittest
from unittest.mock import Mock, patch

import pymysql
from fastapi import HTTPException
import history_store


class ConnectionFailureTest(unittest.TestCase):
    def test_disconnect_remains_a_sanitized_service_error_when_rollback_fails(self):
        database = Mock()
        database.rollback.side_effect = pymysql.InterfaceError(0, '')
        with patch.object(history_store, 'connect', return_value=database):
            with self.assertRaises(HTTPException) as failure:
                with history_store.connection(error_detail='数据库暂不可用'):
                    raise pymysql.OperationalError(2013, 'private connection detail')
        self.assertEqual(failure.exception.status_code, 503)
        self.assertEqual(failure.exception.detail, '数据库暂不可用')
        database.close.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
