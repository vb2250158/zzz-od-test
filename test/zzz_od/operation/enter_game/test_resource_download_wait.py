"""用合成 OCR 帧验证资源下载等待，不连接游戏或创建真实控制器。"""

from unittest.mock import Mock

import pytest

from one_dragon.base.operation.operation_round_result import (
    OperationRoundResult,
    OperationRoundResultEnum,
)
from zzz_od.operation.enter_game.enter_game import EnterGame


@pytest.fixture()
def download_op() -> EnterGame:
    """仅构造节点所需状态，保留真实节点和等待结果实现。"""
    operation = object.__new__(EnterGame)
    operation.force_login = False
    operation.already_login = False
    operation.after_first_enter_click = True
    operation.after_second_enter_click = False
    operation.resource_download_start_time = None
    operation.last_screenshot = None
    operation._after_round_wait = Mock()
    operation.round_by_find_area = Mock(
        return_value=OperationRoundResult(OperationRoundResultEnum.RETRY),
    )
    operation.round_by_find_and_click_area = Mock(
        return_value=OperationRoundResult(OperationRoundResultEnum.SUCCESS),
    )
    operation.round_by_click_area = Mock(
        return_value=OperationRoundResult(OperationRoundResultEnum.SUCCESS),
    )
    operation.match_login_error = Mock(return_value=None)
    operation.check_enter_click_status_text = Mock(return_value=(None, None))
    return operation


@pytest.mark.parametrize('second_click', [False, True])
def test_download_survives_missing_ocr_frames(
    download_op: EnterGame, monkeypatch: pytest.MonkeyPatch, second_click: bool,
) -> None:
    """下载识别后超过十五帧丢字仍等待，计时不因再次识别而重置。"""
    download_op.after_second_enter_click = second_click
    frames = ['资源下载中'] + [None] * 20 + ['资源下载中', None]
    download_op.check_enter_click_status_text.side_effect = [
        (text, None) for text in frames
    ]
    for frame_index in range(len(frames)):
        monkeypatch.setattr('zzz_od.operation.enter_game.enter_game.time.time',
                            Mock(return_value=100 + frame_index * 2))
        result = download_op.check_enter_click_status()
        assert result.result == OperationRoundResultEnum.WAIT
        assert result.status == '资源下载中'
        assert download_op.resource_download_start_time == 100
    download_op.round_by_click_area.assert_not_called()
    download_op.match_login_error.assert_not_called()


@pytest.mark.parametrize('ocr_text', [None, '资源下载中'])
@pytest.mark.parametrize('elapsed', [1199, 1200, 1201])
def test_download_timeout_uses_original_start(
    download_op: EnterGame, monkeypatch: pytest.MonkeyPatch,
    ocr_text: str | None, elapsed: int,
) -> None:
    """文字可见或消失均使用同一个二十分钟边界。"""
    download_op.resource_download_start_time = 100
    download_op.check_enter_click_status_text.return_value = (ocr_text, None)
    monkeypatch.setattr('zzz_od.operation.enter_game.enter_game.time.time',
                        lambda: 100 + elapsed)
    result = download_op.check_enter_click_status()
    if elapsed < EnterGame.MAX_RESOURCE_DOWNLOAD_SECONDS:
        assert result.result == OperationRoundResultEnum.WAIT
        assert download_op.resource_download_start_time == 100
    else:
        assert result.is_fail
        assert result.status == '资源下载超时'
        assert download_op.resource_download_start_time is None


@pytest.mark.parametrize('next_text', ['点击进入游戏', '加载配置数据中', '登录成功'])
def test_download_resumes_on_recognized_state(
    download_op: EnterGame, next_text: str,
) -> None:
    """后续状态有明确文字才结束下载等待并执行原有分支。"""
    download_op.resource_download_start_time = 100
    download_op.check_enter_click_status_text.return_value = (next_text, None)
    result = download_op.check_enter_click_status()
    assert result.status == next_text
    assert download_op.resource_download_start_time is None
    if next_text == '登录成功':
        assert result.is_success
    else:
        assert result.result == OperationRoundResultEnum.WAIT
    if next_text == '点击进入游戏':
        download_op.round_by_click_area.assert_called_once()


def test_data_updated_confirmation_preserved(download_op: EnterGame) -> None:
    """下载完成提示优先处理，确认后返回画面识别并清除下载计时。"""
    download_op.resource_download_start_time = 100
    download_op.round_by_find_area.return_value = OperationRoundResult(
        OperationRoundResultEnum.SUCCESS,
    )
    result = download_op.check_enter_click_status()
    assert result.is_success
    assert result.status == EnterGame.STATUS_GAME_DATA_UPDATED
    assert download_op.resource_download_start_time is None
    download_op.round_by_find_and_click_area.assert_called_once_with(
        None, '打开游戏', '游戏数据更新-确定', retry_wait=1,
    )


def test_unknown_screen_without_download_still_retries(download_op: EnterGame) -> None:
    """未识别过下载时保留原有重试上限，不扩大成无限等待。"""
    result = download_op.check_enter_click_status()
    assert result.result == OperationRoundResultEnum.RETRY
    assert result.status == '进入游戏点击后等待'
