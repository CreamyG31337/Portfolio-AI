from unittest.mock import MagicMock, patch


def _mock_admin_guard(mock_supabase_client_class: MagicMock) -> None:
    """Configure require_admin to pass without external HTTP calls."""
    mock_client_instance = MagicMock()
    mock_rpc_response = MagicMock()
    mock_rpc_response.data = True

    mock_rpc_chain = MagicMock()
    mock_rpc_chain.execute.return_value = mock_rpc_response
    mock_client_instance.supabase.rpc.return_value = mock_rpc_chain

    mock_supabase_client_class.return_value = mock_client_instance


def test_update_user_name_rejects_blank_name(client) -> None:
    with patch('auth.auth_manager.verify_session') as mock_verify, \
         patch('flask_auth_utils.get_supabase_access_token', return_value='fake.jwt.token'), \
         patch('supabase_client.SupabaseClient') as mock_supabase_client_class, \
         patch('flask_auth_utils.can_modify_data_flask', return_value=True):
        mock_verify.return_value = {
            'user_id': 'admin-user-id',
            'email': 'admin@example.com'
        }
        _mock_admin_guard(mock_supabase_client_class)

        client.set_cookie('auth_token', 'test.token.value')
        response = client.post(
            '/api/admin/users/update-name',
            json={'user_id': '123', 'user_email': 'user@example.com', 'full_name': '   '}
        )

        assert response.status_code == 400
        payload = response.get_json()
        assert payload is not None
        assert 'Full name is required' in payload.get('error', '')


def test_update_user_name_updates_profile_and_auth_metadata(client) -> None:
    with patch('auth.auth_manager.verify_session') as mock_verify, \
         patch('flask_auth_utils.get_supabase_access_token', return_value='fake.jwt.token'), \
         patch('supabase_client.SupabaseClient') as mock_supabase_client_class, \
         patch('flask_auth_utils.can_modify_data_flask', return_value=True), \
         patch('app.get_supabase_client') as mock_get_supabase_client, \
         patch('supabase.create_client') as mock_create_client, \
         patch.dict(
             'os.environ',
             {'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_SECRET_KEY': 'service-role-key'},
             clear=False,
         ):
        mock_verify.return_value = {
            'user_id': 'admin-user-id',
            'email': 'admin@example.com'
        }
        _mock_admin_guard(mock_supabase_client_class)

        db_client = MagicMock()
        table_chain = MagicMock()
        update_result = MagicMock()
        update_result.data = [{'user_id': 'user-123'}]
        table_chain.update.return_value = table_chain
        table_chain.eq.return_value = table_chain
        table_chain.execute.return_value = update_result
        db_client.supabase.table.return_value = table_chain
        mock_get_supabase_client.return_value = db_client

        admin_client = MagicMock()
        auth_update_response = MagicMock()
        auth_update_response.user = {'id': 'user-123'}
        admin_client.auth.admin.update_user_by_id.return_value = auth_update_response
        mock_create_client.return_value = admin_client

        client.set_cookie('auth_token', 'test.token.value')
        response = client.post(
            '/api/admin/users/update-name',
            json={'user_id': 'user-123', 'user_email': 'user@example.com', 'full_name': 'Updated Name'}
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload is not None
        assert payload.get('success') is True
        assert payload.get('full_name') == 'Updated Name'

        db_client.supabase.table.assert_called_with('user_profiles')
        table_chain.update.assert_called_once_with({'full_name': 'Updated Name'})
        admin_client.auth.admin.update_user_by_id.assert_called_once_with(
            'user-123',
            {'user_metadata': {'full_name': 'Updated Name'}},
        )


def test_users_list_includes_last_sign_in_at(client) -> None:
    with patch('auth.auth_manager.verify_session') as mock_verify, \
         patch('flask_auth_utils.get_supabase_access_token', return_value='fake.jwt.token'), \
         patch('supabase_client.SupabaseClient') as mock_supabase_client_class, \
         patch('routes.admin_routes._get_cached_users_flask') as mock_get_cached_users:
        mock_verify.return_value = {
            'user_id': 'admin-user-id',
            'email': 'admin@example.com'
        }
        _mock_admin_guard(mock_supabase_client_class)

        mock_get_cached_users.return_value = [{
            'user_id': 'user-123',
            'email': 'user@example.com',
            'full_name': 'Display Name',
            'role': 'user',
            'last_sign_in_at': '2026-02-09T10:15:00+00:00',
            'funds': ['TEST'],
        }]

        client.set_cookie('auth_token', 'test.token.value')
        response = client.get('/api/admin/users/list')

        assert response.status_code == 200
        payload = response.get_json()
        assert payload is not None
        assert 'users' in payload
        assert payload['users'][0]['last_sign_in_at'] == '2026-02-09T10:15:00+00:00'
