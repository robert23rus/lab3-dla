import pytest

from dla.cli import main, parser


@pytest.mark.parametrize('args', [
    ['simulate', '--p', '0'], ['simulate', '--p', 'nan'],
    ['simulate', '--fps', '0'], ['simulate', '--frames', '1'],
    ['experiments', '--replicates', '1'], ['validate', '--trials', '1'],
])
def test_invalid_cli_inputs_fail_before_computation(args):
    with pytest.raises(SystemExit) as exc:
        parser().parse_args(args)
    assert exc.value.code == 2


def test_invalid_grid_has_no_output_side_effect(tmp_path):
    out = tmp_path / 'invalid'
    assert main(['simulate', '--grid-size', '20', '--out', str(out)]) == 2
    assert not out.exists()


def test_missing_saved_cluster_has_clear_error(tmp_path, capsys):
    assert main(['render', '--input', str(tmp_path/'missing.npz')]) == 2
    assert 'Ошибка:' in capsys.readouterr().err
