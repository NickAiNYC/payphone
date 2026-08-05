import logging


class ResourceCleanup:
    @staticmethod
    async def teardown(call_session, voice_pipeline, recorder=None):
        try:
            if recorder:
                await recorder.stop_and_discard()
            if voice_pipeline:
                await voice_pipeline.stop()
            if call_session:
                for sender in call_session.pc.getSenders():
                    if sender.track:
                        sender.track.stop()
                for receiver in call_session.pc.getReceivers():
                    if receiver.track:
                        receiver.track.stop()
                await call_session.pc.close()
        except Exception as e:
            logging.error(f"Cleanup failed: {e}")
