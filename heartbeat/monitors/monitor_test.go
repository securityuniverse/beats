// Licensed to Elasticsearch B.V. under one or more contributor
// license agreements. See the NOTICE file distributed with
// this work for additional information regarding copyright
// ownership. Elasticsearch B.V. licenses this file to you under
// the Apache License, Version 2.0 (the "License"); you may
// not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

package monitors

import (
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	conf "github.com/elastic/elastic-agent-libs/config"
	"github.com/elastic/elastic-agent-libs/mapstr"
	"github.com/elastic/elastic-agent-libs/monitoring"
	"github.com/elastic/go-lookslike"
	"github.com/elastic/go-lookslike/isdef"
	"github.com/elastic/go-lookslike/testslike"
	"github.com/elastic/go-lookslike/validator"

	"github.com/elastic/beats/v7/heartbeat/monitors/plugin"
	"github.com/elastic/beats/v7/heartbeat/scheduler"
	"github.com/elastic/beats/v7/libbeat/management/status"
)

// TestMonitorBasic tests a basic config
func TestMonitorBasic(t *testing.T) {
	testMonitorConfig(
		t,
		mockPluginConf(t, "myId", "myName", "@every 1ms", "http://example.net"),
		mockEventMonitorValidator("myId", "myName"),
	)
}

// TestMonitorBasic tests a config that errors out at plugin creation, but still has stdfields defined.
// This should cause the monitor to run, but only produce error documents
func TestMonitorCfgError(t *testing.T) {
	testMonitorConfig(
		t,
		mockInvalidPluginConfWithStdFields(t, "invalidTestId", "invalidTestName", "@every 10s"),
		lookslike.Compose(
			baseMockEventMonitorValidator("invalidTestId", "invalidTestName", "down"),
			lookslike.MustCompile(mapstr.M{
				"error": mapstr.M{
					"message": isdef.IsStringContaining("missing required field"),
					"type":    "io",
				},
			}),
		),
	)
}

func testMonitorConfig(t *testing.T, conf *conf.C, eventValidator validator.Validator) {
	reg, built, closed := mockPluginsReg()
	pipel := &MockPipeline{}

	sched := scheduler.Create(1, monitoring.NewRegistry(), time.Local, nil, false)
	defer sched.Stop()

	c, err := pipel.Connect()
	require.NoError(t, err)
	mon, err := newMonitor(conf, reg, c, sched.Add, nil, nil)
	require.NoError(t, err)

	mon.Start()

	require.Equal(t, 1, len(pipel.Clients))
	pcClient := pipel.Clients[0]

	timeout := time.Second
	start := time.Now()
	success := false
	for time.Since(start) < timeout && !success {
		count := len(pcClient.PublishedEvents())
		if count >= 1 {
			success = true

			pcClient.Close()

			for _, event := range pcClient.PublishedEvents() {
				testslike.Test(t, eventValidator, event.Fields)
			}
		} else {
			// Let's yield this goroutine so we don't spin
			// This could (possibly?) lock on a single core system otherwise
			time.Sleep(time.Microsecond)
		}
	}

	if !success {
		t.Fatalf("No publishes detected!")
	}

	assert.Equal(t, int64(1), built.Load())
	mon.Stop()

	assert.Equal(t, int64(1), closed.Load())
	assert.Equal(t, true, pcClient.closed)
}

func TestCheckInvalidConfig(t *testing.T) {
	serverMonConf := mockInvalidPluginConf(t)
	reg, built, closed := mockPluginsReg()
	pipel := &MockPipeline{}

	sched := scheduler.Create(1, monitoring.NewRegistry(), time.Local, nil, false)
	defer sched.Stop()

	c, err := pipel.Connect()
	require.NoError(t, err)
	m, err := newMonitor(serverMonConf, reg, c, sched.Add, nil, nil)
	require.Error(t, err)
	// This could change if we decide the contract for newMonitor should always return a monitor
	require.Nil(t, m, "For this test to work we need a nil value for the monitor.")

	// These counters are both zero since this fails at config parse time
	require.Equal(t, int64(0), built.Load())
	require.Equal(t, int64(0), closed.Load())

	require.Error(t, checkMonitorConfig(serverMonConf, reg))
}

type MockStatusReporter struct {
	us func(status status.Status, msg string)
}

func (sr *MockStatusReporter) UpdateStatus(status status.Status, msg string) {
	sr.us(status, msg)
}

func TestStatusReporter(t *testing.T) {
	confMap := map[string]interface{}{
		"type":     "fail",
		"urls":     []string{"http://example.net"},
		"schedule": "@every 1ms",
		"name":     "myName",
		"id":       "myId",
	}
	cfg, err := conf.NewConfigFrom(confMap)
	require.NoError(t, err)

	reg, _, _ := mockPluginsReg()
	pipel := &MockPipeline{}
	monReg := monitoring.NewRegistry()

	mockDegradedPluginFactory := plugin.PluginFactory{
		Name:    "fail",
		Aliases: []string{"failAlias"},
		Make: func(s string, cfg *conf.C) (plugin.Plugin, error) {
			return plugin.Plugin{}, fmt.Errorf("error plugin")
		},
		Stats: plugin.NewPluginCountersRecorder("fail", monReg),
	}
	_ = reg.Add(mockDegradedPluginFactory)

	sched := scheduler.Create(1, monitoring.NewRegistry(), time.Local, nil, true)
	defer sched.Stop()

	c, err := pipel.Connect()
	require.NoError(t, err)
	m, err := newMonitor(cfg, reg, c, sched.Add, nil, nil)
	require.NoError(t, err)

	// Track status marked as failed during run_once execution
	failed := false
	m.SetStatusReporter(&MockStatusReporter{
		us: func(s status.Status, msg string) {
			if s == status.Failed {
				failed = true
			}
		},
	})
	m.Start()

	sched.WaitForRunOnce()

	require.True(t, failed)
}
