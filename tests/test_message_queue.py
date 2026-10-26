"""D13-C 单队列反例：FIFO、单次一条、保留原文及队列隔离。"""

import unittest

from mini_pi import message_queue
from mini_pi.models import Message


class MessageQueueTests(unittest.TestCase):
    def test_empty_queue_returns_no_messages(self):
        queue = message_queue.PendingMessageQueue()
        self.assertEqual(queue.drain_one(), [])

    def test_fifo_one_message_per_delivery_and_no_redelivery(self):
        queue = message_queue.PendingMessageQueue()
        for text in ("第一条", "第二条", "第三条"):
            queue.enqueue(text)
        for text in ("第一条", "第二条", "第三条"):
            self.assertEqual(queue.drain_one(), [Message("user", text)])
        self.assertEqual(queue.drain_one(), [])

    def test_invalid_text_does_not_enter_queue(self):
        queue = message_queue.PendingMessageQueue()
        for text in (None, 123, False, [], "", " \n\t"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    queue.enqueue(text)
        self.assertEqual(queue.drain_one(), [])

    def test_steering_and_follow_up_instances_do_not_share_messages(self):
        steering = message_queue.PendingMessageQueue()
        follow_up = message_queue.PendingMessageQueue()
        steering.enqueue("先解释")
        follow_up.enqueue("最后总结")
        self.assertEqual(steering.drain_one(), [Message("user", "先解释")])
        self.assertEqual(steering.drain_one(), [])
        self.assertEqual(follow_up.drain_one(), [Message("user", "最后总结")])

    def test_nonempty_text_keeps_original_whitespace(self):
        queue = message_queue.PendingMessageQueue()
        queue.enqueue("  先解释\n")
        self.assertEqual(queue.drain_one(), [Message("user", "  先解释\n")])

    def test_new_messages_can_be_queued_after_previous_delivery(self):
        queue = message_queue.PendingMessageQueue()
        queue.enqueue("A")
        self.assertEqual(queue.drain_one(), [Message("user", "A")])
        queue.enqueue("B")
        self.assertEqual(queue.drain_one(), [Message("user", "B")])
        self.assertEqual(queue.drain_one(), [])


if __name__ == "__main__":
    unittest.main()
