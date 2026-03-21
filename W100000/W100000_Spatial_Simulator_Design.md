# W100000. 3D/Room/Spatial Simulator Design

## 1. Objective
Build a directly controllable 3D/room/spatial audio simulator that can generate physically meaningful acoustic scenes for speech separation and downstream audio intelligence tasks.

---

## 2. Requirement Summary
The simulator shall:
- represent room geometry and material properties,
- place and move sound sources and microphones in 3D space,
- simulate propagation, reflection, absorption, and occlusion,
- support mono, binaural, array, and multi-channel capture,
- model device/channel imperfections,
- export synchronized waveforms and scene metadata.

---

## 3. Integrated Capability Derivation

### IC-W1-01. 3D acoustic scene definition
The system shall define all physical scene elements required for audio simulation.

### IC-W1-02. Acoustic propagation and rendering
The system shall transform scene state into channel-wise audio observations.

### IC-W1-03. Dynamic scene evolution
The system shall support time-varying source, listener, and microphone trajectories.

### IC-W1-04. Sensor/device realism modeling
The system shall emulate practical microphone and capture-chain distortions.

### IC-W1-05. Simulator orchestration and export
The system shall execute simulation jobs and package outputs for later data generation and learning.

---

## 4. Integrated Capability Decomposition

## W110000. Scene world modeling
### W111000. Room geometry modeling
### W112000. Surface/material acoustic property modeling
### W113000. Object placement and obstacle modeling
### W114000. Coordinate system and transform management

## W120000. Acoustic propagation engine
### W121000. Direct-path computation
### W122000. Reflection and reverberation computation
### W123000. Diffraction/occlusion approximation
### W124000. RIR/BRIR generation and rendering

## W130000. Dynamic motion simulation
### W131000. Source trajectory generation
### W132000. Microphone/listener trajectory generation
### W133000. Time-varying geometry synchronization
### W134000. Dynamic rendering control

## W140000. Capture device realism
### W141000. Microphone response modeling
### W142000. Array geometry/error modeling
### W143000. Electronic noise and gain modeling
### W144000. Codec/channel impairment modeling

## W150000. Simulator control and packaging
### W151000. Job configuration schema
### W152000. Batch execution control
### W153000. Metadata export
### W154000. Validation visualization and debugging tools

---

## 5. Unit Function Derivation

## W111000. Room geometry modeling
- **UF-W111-01**: Define room primitive types (shoebox, corridor, hall, custom mesh)
- **UF-W111-02**: Import CAD/mesh geometry
- **UF-W111-03**: Validate manifold/closure and simulation-ready mesh status
- **UF-W111-04**: Generate room bounding volumes and collision regions

## W112000. Surface/material acoustic property modeling
- **UF-W112-01**: Register material classes by surface type
- **UF-W112-02**: Assign frequency-dependent absorption/scattering coefficients
- **UF-W112-03**: Support stochastic material variation by scenario seed
- **UF-W112-04**: Export material map per scene

## W113000. Object placement and obstacle modeling
- **UF-W113-01**: Place furniture/partition/obstacle objects
- **UF-W113-02**: Tag objects as reflective, absorptive, or occluding
- **UF-W113-03**: Enforce collision-aware placement constraints
- **UF-W113-04**: Serialize object layout state

## W114000. Coordinate system and transform management
- **UF-W114-01**: Define global room coordinate frame
- **UF-W114-02**: Convert object/source/mic local frames to world frame
- **UF-W114-03**: Time-index transforms for moving entities
- **UF-W114-04**: Validate transform consistency and unit conventions

## W121000. Direct-path computation
- **UF-W121-01**: Compute source-to-mic distance and delay
- **UF-W121-02**: Compute distance attenuation
- **UF-W121-03**: Compute direction-of-arrival per channel
- **UF-W121-04**: Apply air attenuation and optional Doppler handling

## W122000. Reflection and reverberation computation
- **UF-W122-01**: Early reflection path estimation
- **UF-W122-02**: Late reverberation tail modeling
- **UF-W122-03**: Frequency-dependent reverberation shaping
- **UF-W122-04**: Per-room RT60 target fitting

## W123000. Diffraction/occlusion approximation
- **UF-W123-01**: Visibility test between source and receiver
- **UF-W123-02**: Occlusion loss estimation
- **UF-W123-03**: Edge diffraction approximation for partial blockage
- **UF-W123-04**: Dynamic occlusion update with moving objects/entities

## W124000. RIR/BRIR generation and rendering
- **UF-W124-01**: Generate static RIR for source-mic pair
- **UF-W124-02**: Generate binaural/BRIR output for head/listener state
- **UF-W124-03**: Segment-wise dynamic RIR interpolation
- **UF-W124-04**: Render waveform by convolution/update scheduling

## W131000. Source trajectory generation
- **UF-W131-01**: Define motion primitives (linear, random walk, waypoint, conversational)
- **UF-W131-02**: Generate velocity/orientation profiles
- **UF-W131-03**: Enforce path constraints within room geometry
- **UF-W131-04**: Export time-stamped source trajectories

## W132000. Microphone/listener trajectory generation
- **UF-W132-01**: Define static, handheld, wearable, robot, and array-mounted motion modes
- **UF-W132-02**: Generate head rotation/orientation traces
- **UF-W132-03**: Model jitter and pose estimation error
- **UF-W132-04**: Export receiver pose sequence

## W133000. Time-varying geometry synchronization
- **UF-W133-01**: Synchronize scene state by simulation tick
- **UF-W133-02**: Update active transform graph
- **UF-W133-03**: Manage event timing for speech start/stop and motion change
- **UF-W133-04**: Validate temporal alignment across all entities

## W134000. Dynamic rendering control
- **UF-W134-01**: Trigger re-render by state-change threshold
- **UF-W134-02**: Select segment length for dynamic convolution
- **UF-W134-03**: Manage trade-off between accuracy and runtime
- **UF-W134-04**: Log render statistics for profiling

## W141000. Microphone response modeling
- **UF-W141-01**: Apply frequency response profile
- **UF-W141-02**: Model sensitivity variation per channel
- **UF-W141-03**: Apply directional pickup pattern
- **UF-W141-04**: Inject manufacturing tolerance variation

## W142000. Array geometry/error modeling
- **UF-W142-01**: Define array topology templates
- **UF-W142-02**: Perturb nominal microphone positions
- **UF-W142-03**: Model clock skew/sample mismatch
- **UF-W142-04**: Export effective array geometry metadata

## W143000. Electronic noise and gain modeling
- **UF-W143-01**: Add sensor self-noise floor
- **UF-W143-02**: Apply gain and AGC behavior
- **UF-W143-03**: Clip/saturate waveform under overload
- **UF-W143-04**: Model channel-dependent SNR profiles

## W144000. Codec/channel impairment modeling
- **UF-W144-01**: Apply bandwidth limitation
- **UF-W144-02**: Apply lossy codec artifact simulation
- **UF-W144-03**: Apply packet loss/jitter simulation for streaming mode
- **UF-W144-04**: Tag impairment conditions in metadata

## W151000. Job configuration schema
- **UF-W151-01**: Define scene YAML/JSON schema
- **UF-W151-02**: Validate configuration completeness
- **UF-W151-03**: Support seed-based deterministic reproduction
- **UF-W151-04**: Version control configuration schema

## W152000. Batch execution control
- **UF-W152-01**: Queue simulation jobs
- **UF-W152-02**: Parallelize scene rendering
- **UF-W152-03**: Resume interrupted generation jobs
- **UF-W152-04**: Track runtime/resource usage

## W153000. Metadata export
- **UF-W153-01**: Export room/source/mic parameters
- **UF-W153-02**: Export trajectories and event timeline
- **UF-W153-03**: Export acoustic summary (RT60, DRR, SNR, DOA)
- **UF-W153-04**: Write manifest for downstream dataset builder

## W154000. Validation visualization and debugging tools
- **UF-W154-01**: Plot room layout and paths
- **UF-W154-02**: Visualize RIR/BRIR statistics
- **UF-W154-03**: Inspect waveform/channel outputs
- **UF-W154-04**: Provide scene replay for debugging

---

## 6. Interfaces and Outputs
- Scene config files
- Rendered multi-channel audio
- Clean source references
- RIR/BRIR assets
- Room and trajectory metadata
- Acoustic summary tables

---

## 7. Verification Focus
- Geometry validity
- Acoustic plausibility
- Temporal consistency in dynamic scenes
- Reproducibility by seed/config
- Runtime scalability for later dataset generation
